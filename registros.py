"""Agregar, editar y eliminar registros uno por uno.

Arma los campos de cada formulario a partir de las columnas de la tabla
y reutiliza las mismas revisiones de la carga de archivos (importar.py).
"""

import urllib.parse

import pandas as pd

import datos as fuente
import importar
from exportar import COLUMNAS as COLUMNAS_EXCEL

# Columnas que deben elegirse de una lista fija (iguales a los filtros por estado)
OPCIONES_FIJAS = {
    ("pedidos", "estado_pedido"): ["Pendiente", "En preparación", "En ruta", "Entregado", "Cancelado"],
    ("vehiculos", "estado"): ["Disponible", "En ruta", "Mantención", "Fuera de servicio"],
    ("conductores", "estado"): ["Activo", "Inactivo", "Licencia médica", "Vacaciones"],
    ("rutas", "estado"): ["Activa", "Restringida", "Suspendida"],
    ("incidentes", "resuelto"): ["No", "En seguimiento", "Sí"],
    ("entregas", "entrega_a_tiempo"): ["Sí", "No"],
    ("entregas", "estado_entrega"): ["Entregada", "Retrasada"],
}

# Columnas que apuntan a otro registro: (tabla, columna que se muestra)
REFERENCIAS = {
    "vehiculo_id": ("vehiculos", "patente"),
    "conductor_id": ("conductores", "nombre_conductor"),
    "ruta_id": ("rutas", "nombre_ruta"),
    "cliente_id": ("clientes", "nombre_cliente"),
}

# Columna que identifica cada registro en las listas (además del ID)
COLUMNA_PRINCIPAL = {
    "vehiculos": "patente",
    "conductores": "nombre_conductor",
    "rutas": "nombre_ruta",
    "clientes": "nombre_cliente",
    "pedidos": "estado_pedido",
    "entregas": "estado_entrega",
    "mantenciones": "tipo_mantencion",
    "combustible": "estacion_carga",
    "incidentes": "tipo_incidente",
}


def _etiqueta(tabla, columna):
    for nombre, titulo, _ in COLUMNAS_EXCEL.get(tabla, []):
        if nombre == columna:
            return titulo
    texto = columna.replace("_id", "").replace("_", " ").strip()
    return texto[:1].upper() + texto[1:]


def _a_fecha_iso(valor):
    """Valor guardado (20260108 o "08/01/2026") -> "2026-01-08" para <input type=date>."""
    fecha = importar._fecha(valor)
    return "" if fecha in (None, "error") else fecha.strftime("%Y-%m-%d")


def campos(tabla, D, registro=None):
    """Lista de campos del formulario, con su tipo, opciones y valor actual."""

    demo = fuente.demo()
    lista = []

    for columna in fuente.TABLAS[tabla][1]:
        valor = None if registro is None else registro.get(columna)
        if valor is not None and isinstance(valor, float) and pd.isna(valor):
            valor = None

        campo = {
            "nombre": columna,
            "etiqueta": _etiqueta(tabla, columna),
            "obligatorio": columna == importar.clave(tabla),
            "tipo": "texto",
            "opciones": [],
            "sugerencias": [],
        }

        if columna in importar.FECHAS_NUMERO or columna in importar.FECHAS_TEXTO:
            campo["tipo"] = "fecha"
            valor = _a_fecha_iso(valor) if valor is not None else ""

        elif (tabla, columna) in OPCIONES_FIJAS:
            campo["tipo"] = "opciones"
            campo["opciones"] = [(o, o) for o in OPCIONES_FIJAS[(tabla, columna)]]

        elif columna in REFERENCIAS and columna != importar.clave(tabla):
            otra_tabla, mostrar = REFERENCIAS[columna]
            df = getattr(D, otra_tabla)
            if len(df):
                campo["tipo"] = "opciones"
                campo["opciones"] = [
                    (str(int(fila[columna])), f"{fila[mostrar]} ({int(fila[columna])})")
                    for _, fila in df.sort_values(mostrar, na_position="last").iterrows()
                    if not pd.isna(fila[columna])
                ]
            else:
                campo["tipo"] = "entero"
                campo["ayuda"] = f"Aún no tienes {importar.NOMBRES[otra_tabla].lower()}; escribe el número."

        elif columna in importar.DECIMALES:
            campo["tipo"] = "decimal"

        elif columna in fuente.NUMERICAS:
            campo["tipo"] = "entero"

        else:
            # Sugerencias: valores usados en la demo y en la empresa
            valores = set()
            for origen in (getattr(demo, tabla), getattr(D, tabla)):
                serie = origen[columna].dropna()
                if serie.nunique() <= 25:
                    valores.update(str(v) for v in serie.unique())
            campo["sugerencias"] = sorted(valores)

        if valor is not None and campo["tipo"] in ("entero", "opciones") and isinstance(valor, float) and valor.is_integer():
            valor = int(valor)
        campo["valor"] = "" if valor is None else str(valor)

        lista.append(campo)

    return lista


def siguiente_id(tabla, D):
    """ID sugerido para un registro nuevo (el mayor + 1)."""
    serie = getattr(D, tabla)[importar.clave(tabla)].dropna()
    return int(serie.max()) + 1 if len(serie) else 1


def buscar(tabla, D, id_registro):
    df = getattr(D, tabla)
    fila = df[df[importar.clave(tabla)] == id_registro]
    return None if fila.empty else fila.iloc[0].to_dict()


def validar_formulario(tabla, formulario):
    """Valores del formulario -> registro listo para guardar (o ErrorCarga)."""

    valores = {c: (formulario.get(c, "").strip() or None) for c in fuente.TABLAS[tabla][1]}
    df = pd.DataFrame([valores], dtype=object)

    try:
        registros, _ = importar.validar(df, tabla)
    except importar.ErrorCarga as error:
        # En un formulario no hay "filas": se quita esa parte del mensaje
        texto = str(error).replace("Revisa el archivo:\n", "").replace("Fila 2, ", "").replace("Fila 2: ", "")
        for columna in fuente.TABLAS[tabla][1]:
            texto = texto.replace(f"columna '{columna}'", f"«{_etiqueta(tabla, columna)}»")
            texto = texto.replace(f"falta '{columna}'", f"falta «{_etiqueta(tabla, columna)}»")
        raise importar.ErrorCarga(texto) from error

    return registros[0]


def eliminar(empresa_id, tabla, id_registro):
    consulta = urllib.parse.urlencode({
        "empresa_id": f"eq.{empresa_id}",
        importar.clave(tabla): f"eq.{id_registro}",
    })
    importar._llamar("DELETE", f"/rest/v1/{tabla}?{consulta}")
    fuente.olvidar(empresa_id)
