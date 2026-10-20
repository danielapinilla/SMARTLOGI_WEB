"""Carga de datos de una empresa desde Excel o CSV.

1. leer_archivo(): abre el Excel/CSV.
2. validar(): ordena columnas, convierte números y fechas, y avisa
   exactamente en qué fila hay un problema.
3. guardar(): sube las filas a Supabase para esa empresa.
"""

import io
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
import xlsxwriter

import datos as fuente
from exportar import COLUMNAS as COLUMNAS_EXCEL

MAX_FILAS = 20000
LOTE = 500  # filas por envío a Supabase

NOMBRES = {
    "vehiculos": "Vehículos",
    "conductores": "Conductores",
    "rutas": "Rutas",
    "clientes": "Clientes",
    "pedidos": "Pedidos",
    "entregas": "Entregas",
    "mantenciones": "Mantenciones",
    "combustible": "Combustible",
    "incidentes": "Incidentes",
}

DESCRIPCIONES = {
    "vehiculos": "Tu flota: patente, tipo, marca, capacidad y estado.",
    "conductores": "Tu equipo de conductores, su licencia y estado.",
    "rutas": "Rutas habituales: origen, destino, distancia y tráfico.",
    "clientes": "Las personas y empresas a las que les entregas.",
    "pedidos": "Cada pedido: cliente, fecha, valor y estado.",
    "entregas": "Cada viaje: conductor, vehículo, ruta, tiempos y retraso.",
    "mantenciones": "Mantenciones de cada vehículo, costo y resultado.",
    "combustible": "Cargas de combustible: litros, precio y kilometraje.",
    "incidentes": "Incidentes en ruta: tipo, gravedad, costo y si se resolvió.",
}

# Fechas guardadas como número AAAAMMDD
FECHAS_NUMERO = {"fecha_pedido_id", "fecha_salida_id", "fecha_entrega_id",
                 "fecha_mantencion_id", "fecha_id", "fecha_incidente_id"}

# Fechas guardadas como texto dd/mm/aaaa (igual que en la demo)
FECHAS_TEXTO = {"fecha_ingreso", "fecha_alta", "fecha_registro"}

# Columnas numéricas con decimales (el resto de las numéricas son enteras)
DECIMALES = {"peso_total_kg", "valor_pedido", "distancia_km", "costo",
             "litros_cargados", "precio_litro", "costo_total", "costo_estimado"}


class ErrorCarga(Exception):
    """Problema con el archivo, con un mensaje para mostrar a la persona."""


# =========================
# NOMBRES DE COLUMNAS
# =========================

def _normalizar(texto):
    """'ID Pedido' -> 'id_pedido' ; 'Peso (kg)' -> 'peso_kg'"""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")
    return texto


def _alias(tabla):
    """Nombres aceptados para cada columna: el técnico y el título del Excel exportado."""
    alias = {}
    for columna in fuente.TABLAS[tabla][1]:
        alias[_normalizar(columna)] = columna
    for columna, titulo, _ in COLUMNAS_EXCEL.get(tabla, []):
        if columna in fuente.TABLAS[tabla][1]:
            alias.setdefault(_normalizar(titulo), columna)
    return alias


def clave(tabla):
    """Columna que identifica cada fila (ej. pedido_id)."""
    return fuente.TABLAS[tabla][1][0]


# =========================
# PLANTILLA
# =========================

def plantilla(tabla):
    """Excel con las columnas correctas, 3 filas de ejemplo e instrucciones."""

    columnas = fuente.TABLAS[tabla][1]
    ejemplo = fuente.demo().__dict__[tabla][columnas].head(3)

    archivo = io.BytesIO()
    libro = xlsxwriter.Workbook(archivo, {"in_memory": True})
    encabezado = libro.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#15253F"})
    negrita = libro.add_format({"bold": True})

    hoja = libro.add_worksheet("Datos")
    for numero, columna in enumerate(columnas):
        hoja.write(0, numero, columna, encabezado)
        hoja.set_column(numero, numero, max(len(columna) + 3, 14))
        for fila, valor in enumerate(ejemplo[columna].tolist(), start=1):
            if pd.isna(valor):
                continue
            if isinstance(valor, float) and valor.is_integer():
                valor = int(valor)
            hoja.write(fila, numero, valor)
    hoja.freeze_panes(1, 0)

    ayuda = libro.add_worksheet("Instrucciones")
    ayuda.set_column(0, 0, 26)
    ayuda.set_column(1, 1, 70)
    lineas = [
        ("Cómo usar esta plantilla", ""),
        ("1.", "Borra las 3 filas de ejemplo de la hoja 'Datos' y escribe tus datos."),
        ("2.", "No cambies los nombres de la primera fila."),
        ("3.", f"La columna '{clave(tabla)}' es obligatoria y no puede repetirse."),
        ("4.", "Guarda el archivo y súbelo en SmartLogic > Cargar datos."),
        ("", ""),
        ("Columna", "Qué escribir"),
    ]
    for columna in columnas:
        if columna in FECHAS_NUMERO or columna in FECHAS_TEXTO:
            detalle = "Fecha. Ej: 08-01-2026 (también sirve 08/01/2026 o 20260108)"
        elif columna in DECIMALES:
            detalle = "Número (puede tener decimales). Ej: 1234,5 o $91.032"
        elif columna in fuente.NUMERICAS:
            detalle = "Número entero. Ej: 12"
        else:
            detalle = "Texto"
        if columna == clave(tabla):
            detalle += " · OBLIGATORIO, sin repetir"
        lineas.append((columna, detalle))

    for fila, (a, b) in enumerate(lineas):
        ayuda.write(fila, 0, a, negrita if fila in (0, 6) or a in fuente.TABLAS[tabla][1] else None)
        ayuda.write(fila, 1, b)

    libro.close()
    archivo.seek(0)
    return archivo


# =========================
# LEER Y VALIDAR
# =========================

def leer_archivo(contenido, nombre_archivo):
    """bytes del archivo -> DataFrame con todo como texto/valor original."""

    extension = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""

    try:
        if extension in ("xlsx", "xlsm", "xls"):
            libro = pd.read_excel(io.BytesIO(contenido), sheet_name=None, dtype=object)
            # Si tiene hoja "Datos" (la plantilla), se usa esa; si no, la primera
            df = libro.get("Datos", next(iter(libro.values())))
        elif extension in ("csv", "txt"):
            for codificacion in ("utf-8-sig", "latin-1"):
                try:
                    texto = contenido.decode(codificacion)
                    break
                except UnicodeDecodeError:
                    continue
            # Detecta si las columnas van separadas por ; (Excel en español) o ,
            separador = ";" if texto.split("\n", 1)[0].count(";") > texto.split("\n", 1)[0].count(",") else ","
            df = pd.read_csv(io.StringIO(texto), sep=separador, dtype=object)
        else:
            raise ErrorCarga("El archivo debe ser Excel (.xlsx) o CSV (.csv).")
    except ErrorCarga:
        raise
    except Exception as error:
        raise ErrorCarga("No se pudo leer el archivo. Revisa que sea un Excel o CSV válido.") from error

    # Quitar filas y columnas completamente vacías
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


def _numero(valor):
    """'$91.032' -> 91032 ; '1.234,5' -> 1234.5 ; 12 -> 12. None si no se puede."""

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = str(valor).strip().replace("$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "")

    try:
        return float(texto)
    except ValueError:
        return "error"


def _fecha(valor):
    """Cualquier formato común -> pd.Timestamp (None si vacío, 'error' si no se entiende)."""

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, pd.Timestamp) or hasattr(valor, "year"):
        return pd.Timestamp(valor)

    texto = str(valor).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    if not texto:
        return None

    # Atajo para el formato más común (AAAAMMDD): mucho más rápido
    if len(texto) == 8 and texto.isdigit():
        try:
            return pd.Timestamp(int(texto[:4]), int(texto[4:6]), int(texto[6:]))
        except ValueError:
            return "error"

    formatos = ["%Y%m%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"]
    for formato in formatos:
        try:
            return pd.to_datetime(texto, format=formato)
        except (ValueError, TypeError):
            continue
    return "error"


def _buscar_encabezado(df, alias):
    """Si los encabezados no están en la primera fila (ej. el Excel exportado
    por SmartLogic tiene un título arriba), los busca en las primeras 10 filas.

    Devuelve (df con los encabezados correctos, filas que se saltaron).
    """

    reconocidos = sum(_normalizar(c) in alias for c in df.columns)
    if reconocidos >= 2:
        return df, 0

    for i in range(min(10, len(df))):
        valores = [_normalizar(v) for v in df.iloc[i].tolist() if not pd.isna(v)]
        if sum(v in alias for v in valores) >= 2:
            nuevo = df.iloc[i + 1:].copy()
            nuevo.columns = df.iloc[i].tolist()
            return nuevo.dropna(how="all"), i + 1

    return df, 0


def validar(df, tabla):
    """Devuelve (filas listas para guardar, avisos). Lanza ErrorCarga si hay errores."""

    if tabla not in fuente.TABLAS:
        raise ErrorCarga("Tabla desconocida.")

    if df.empty:
        raise ErrorCarga("El archivo no tiene filas con datos.")

    if len(df) > MAX_FILAS:
        raise ErrorCarga(f"El archivo tiene {len(df):,} filas; el máximo por carga es {MAX_FILAS:,}.".replace(",", "."))

    # ---------- Columnas ----------
    alias = _alias(tabla)
    df, saltadas = _buscar_encabezado(df, alias)
    renombres, ignoradas = {}, []
    for original in df.columns:
        destino = alias.get(_normalizar(original))
        if destino and destino not in renombres.values():
            renombres[original] = destino
        else:
            ignoradas.append(str(original))

    df = df.rename(columns=renombres)[list(renombres.values())]
    id_col = clave(tabla)

    if id_col not in df.columns:
        raise ErrorCarga(
            f"Falta la columna obligatoria '{id_col}'. Descarga la plantilla para ver los nombres correctos."
        )

    avisos = []
    if ignoradas:
        avisos.append("Se ignoraron columnas que no se reconocen: " + ", ".join(ignoradas[:8]) + ("…" if len(ignoradas) > 8 else ""))

    faltantes = [c for c in fuente.TABLAS[tabla][1] if c not in df.columns]
    if faltantes:
        avisos.append("Columnas que no venían (quedan vacías): " + ", ".join(faltantes))

    # ---------- Valores ----------
    errores = []
    limpias = {}

    for columna in df.columns:
        valores = []
        for posicion, valor in enumerate(df[columna].tolist()):
            fila_excel = posicion + 2 + saltadas  # +1 encabezado, +1 porque Excel parte en 1

            if columna in FECHAS_NUMERO or columna in FECHAS_TEXTO:
                fecha = _fecha(valor)
                if fecha == "error":
                    errores.append(f"Fila {fila_excel}, columna '{columna}': la fecha «{valor}» no se entiende.")
                    valores.append(None)
                elif fecha is None:
                    valores.append(None)
                elif columna in FECHAS_NUMERO:
                    valores.append(int(fecha.strftime("%Y%m%d")))
                else:
                    valores.append(fecha.strftime("%d/%m/%Y"))

            elif columna in fuente.NUMERICAS:
                numero = _numero(valor)
                if numero == "error":
                    errores.append(f"Fila {fila_excel}, columna '{columna}': «{valor}» no es un número.")
                    valores.append(None)
                elif numero is None:
                    valores.append(None)
                elif columna in DECIMALES:
                    valores.append(round(numero, 4))
                else:
                    valores.append(int(round(numero)))

            else:
                texto = None if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor).strip()
                if texto and texto.endswith(".0") and texto[:-2].isdigit():
                    texto = texto[:-2]  # Excel guarda "2023" como 2023.0
                valores.append(texto or None)

            if len(errores) >= 10:
                break
        limpias[columna] = valores
        if len(errores) >= 10:
            break

    # Identificador obligatorio
    for posicion, valor in enumerate(limpias.get(id_col, [])):
        if valor is None and len(errores) < 10:
            errores.append(f"Fila {posicion + 2 + saltadas}: falta '{id_col}' (es obligatorio).")

    if errores:
        raise ErrorCarga("Revisa el archivo:\n" + "\n".join(errores[:10]))

    filas = pd.DataFrame(limpias)

    duplicados = int(filas[id_col].duplicated(keep="last").sum())
    if duplicados:
        filas = filas.drop_duplicates(subset=id_col, keep="last")
        avisos.append(f"Había {duplicados} fila(s) con '{id_col}' repetido; se dejó la última de cada una.")

    registros = [
        {c: (None if (isinstance(v, float) and pd.isna(v)) else v) for c, v in fila.items()}
        for fila in filas.to_dict("records")
    ]
    return registros, avisos


# =========================
# GUARDAR EN SUPABASE
# =========================

def _llamar(metodo, ruta, datos=None, cabeceras=None):
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/").removesuffix("/rest/v1")
    clave_servicio = os.environ.get("SUPABASE_SERVICE_KEY", "")
    encabezados = {"apikey": clave_servicio, "Authorization": f"Bearer {clave_servicio}",
                   "Content-Type": "application/json"}
    encabezados.update(cabeceras or {})
    peticion = urllib.request.Request(
        f"{url}{ruta}", data=json.dumps(datos).encode() if datos is not None else None,
        headers=encabezados, method=metodo,
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        try:
            detalle = json.load(error).get("message", "")
        except ValueError:
            detalle = ""
        raise ErrorCarga(f"La base de datos rechazó los datos. {detalle}".strip()) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorCarga("No se pudo conectar con la base de datos. Intenta de nuevo.") from error


def guardar(empresa_id, tabla, registros, reemplazar=False):
    """Sube las filas de la empresa. Con reemplazar=True, primero borra las anteriores."""

    if reemplazar:
        consulta = urllib.parse.urlencode({"empresa_id": f"eq.{empresa_id}"})
        _llamar("DELETE", f"/rest/v1/{tabla}?{consulta}")

    # "merge-duplicates": si el identificador ya existe, se actualiza esa fila
    for inicio in range(0, len(registros), LOTE):
        lote = [dict(fila, empresa_id=empresa_id) for fila in registros[inicio:inicio + LOTE]]
        _llamar("POST", f"/rest/v1/{tabla}", lote,
                {"Prefer": "resolution=merge-duplicates,return=minimal"})

    fuente.olvidar(empresa_id)
    return len(registros)
