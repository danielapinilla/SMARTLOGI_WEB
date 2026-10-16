"""Exportación a Excel (.xlsx) de las tablas de SmartLogic.

Cada sección define qué columnas salen, con qué título y en qué formato,
para que el archivo quede listo para usar (fechas reales, montos en pesos,
filtros en los encabezados y colores de la marca).
"""

import io
import unicodedata
from datetime import datetime

import pandas as pd
import xlsxwriter

# Formatos de número de Excel. Excel muestra los separadores según el idioma del equipo
# (en Chile: 1.234 y 12,5).
FORMATOS = {
    "texto": "@",
    "entero": "#,##0",
    "decimal": "#,##0.00",
    "pesos": '"$"#,##0',
    "fecha": "dd-mm-yyyy",
}

# (columna en los datos, título en el Excel, formato)
COLUMNAS = {
    "pedidos": [
        ("pedido_id", "ID Pedido", "texto"),
        ("cliente_id", "ID Cliente", "texto"),
        ("nombre_cliente", "Cliente", "texto"),
        ("fecha_pedido_id", "Fecha", "fecha"),
        ("tipo_servicio", "Servicio", "texto"),
        ("cantidad_paquetes", "Paquetes", "entero"),
        ("peso_total_kg", "Peso (kg)", "decimal"),
        ("prioridad", "Prioridad", "texto"),
        ("valor_pedido", "Valor", "pesos"),
        ("comuna_entrega", "Comuna entrega", "texto"),
        ("estado_pedido", "Estado", "texto"),
    ],
    "vehiculos": [
        ("vehiculo_id", "ID Vehículo", "texto"),
        ("patente", "Patente", "texto"),
        ("tipo_vehiculo", "Tipo", "texto"),
        ("marca", "Marca", "texto"),
        ("modelo", "Modelo", "texto"),
        ("anio", "Año", "texto"),
        ("capacidad_kg", "Capacidad (kg)", "entero"),
        ("combustible", "Combustible", "texto"),
        ("fecha_alta", "Fecha de alta", "fecha"),
        ("estado", "Estado", "texto"),
    ],
    "conductores": [
        ("conductor_id", "ID Conductor", "texto"),
        ("nombre_conductor", "Nombre", "texto"),
        ("fecha_ingreso", "Fecha ingreso", "fecha"),
        ("experiencia_anios", "Experiencia (años)", "entero"),
        ("tipo_licencia", "Licencia", "texto"),
        ("estado", "Estado", "texto"),
    ],
    "rutas": [
        ("ruta_id", "ID Ruta", "texto"),
        ("nombre_ruta", "Nombre ruta", "texto"),
        ("comuna_origen", "Origen", "texto"),
        ("comuna_destino", "Destino", "texto"),
        ("distancia_km", "Distancia (km)", "decimal"),
        ("tiempo_estimado_min", "Tiempo estimado (min)", "entero"),
        ("nivel_trafico_habitual", "Tráfico habitual", "texto"),
        ("tipo_ruta", "Tipo de ruta", "texto"),
        ("peajes", "Peajes", "entero"),
        ("estado", "Estado", "texto"),
    ],
    "mantenciones": [
        ("mantencion_id", "ID Mantención", "texto"),
        ("patente", "Patente", "texto"),
        ("tipo_mantencion", "Tipo", "texto"),
        ("descripcion", "Descripción", "texto"),
        ("fecha_mantencion_id", "Fecha", "fecha"),
        ("costo", "Costo", "pesos"),
        ("kilometraje", "Kilometraje", "entero"),
        ("dias_fuera_servicio", "Días fuera de servicio", "entero"),
        ("taller", "Taller", "texto"),
        ("resultado", "Resultado", "texto"),
    ],
    "combustible": [
        ("combustible_id", "ID Registro", "texto"),
        ("patente", "Patente", "texto"),
        ("fecha_id", "Fecha", "fecha"),
        ("tipo_combustible", "Combustible", "texto"),
        ("litros_cargados", "Litros", "decimal"),
        ("precio_litro", "Precio litro", "pesos"),
        ("costo_total", "Costo total", "pesos"),
        ("kilometraje_actual", "Kilometraje", "entero"),
        ("estacion_carga", "Estación", "texto"),
    ],
    "incidentes": [
        ("incidente_id", "ID Incidente", "texto"),
        ("entrega_id", "ID Entrega", "texto"),
        ("fecha_incidente_id", "Fecha", "fecha"),
        ("patente", "Patente", "texto"),
        ("nombre_conductor", "Conductor", "texto"),
        ("tipo_incidente", "Tipo", "texto"),
        ("gravedad", "Gravedad", "texto"),
        ("descripcion", "Descripción", "texto"),
        ("tiempo_perdido_min", "Tiempo perdido (min)", "entero"),
        ("costo_estimado", "Costo estimado", "pesos"),
        ("estado_incidente", "Estado", "texto"),
    ],
}

TITULOS = {
    "pedidos": "Pedidos",
    "vehiculos": "Vehículos",
    "conductores": "Conductores",
    "rutas": "Rutas",
    "mantenciones": "Mantenciones",
    "combustible": "Combustible",
    "incidentes": "Incidentes",
}

COLOR_MARINO = "15253F"
FILA_ENCABEZADO = 4  # filas 1-2: título y detalle; fila 3 en blanco


def _a_fecha(serie):
    """Convierte 20250108 o "08/01/2025" a fecha real (vacío si no se puede)."""

    texto = serie.astype(str).str.strip()

    if texto.str.fullmatch(r"\d{8}").all():
        return pd.to_datetime(texto, format="%Y%m%d", errors="coerce")

    return pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")


def nombre_archivo(seccion, filtro, fecha):
    """smartlogic_pedidos_cancelado_2026-10-15.xlsx (sin tildes ni espacios)."""

    partes = ["smartlogic", seccion]
    if filtro and filtro != "Todos":
        partes.append(filtro)

    texto = "_".join(partes).lower().replace(" ", "-")
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return f"{texto}_{fecha:%Y-%m-%d}.xlsx"


def crear_excel(df, seccion, filtro=None, fecha=None):
    """Devuelve un archivo .xlsx en memoria (BytesIO) con la tabla formateada."""

    fecha = fecha or datetime.now()
    columnas = [c for c in COLUMNAS[seccion] if c[0] in df.columns]
    titulo = TITULOS[seccion]

    datos = df[[c[0] for c in columnas]].copy()

    for columna, _, formato in columnas:
        if formato == "fecha":
            datos[columna] = _a_fecha(datos[columna])
        elif formato == "texto":
            datos[columna] = datos[columna].map(lambda v: "" if pd.isna(v) else str(v))

    archivo = io.BytesIO()
    libro = xlsxwriter.Workbook(archivo, {
        "in_memory": True,
        "nan_inf_to_errors": True,
        "default_date_format": FORMATOS["fecha"],
    })
    hoja = libro.add_worksheet(titulo)

    estilo_titulo = libro.add_format({"bold": True, "font_size": 14, "font_color": "#" + COLOR_MARINO})
    estilo_detalle = libro.add_format({"font_size": 10, "font_color": "#6B7585"})
    estilo_encabezado = libro.add_format({
        "bold": True, "font_color": "#FFFFFF", "bg_color": "#" + COLOR_MARINO, "valign": "vcenter",
    })
    estilos = {nombre: libro.add_format({"num_format": formato}) for nombre, formato in FORMATOS.items()}

    # ---------- Título y detalle ----------
    hoja.write(0, 0, f"SmartLogic · {titulo}", estilo_titulo)

    detalle = f"{len(datos):,} registros".replace(",", ".")
    if filtro and filtro != "Todos":
        detalle += f" · Filtro: {filtro}"
    detalle += f" · Descargado el {fecha:%d-%m-%Y %H:%M}"
    hoja.write(1, 0, detalle, estilo_detalle)

    fila_encabezado = FILA_ENCABEZADO - 1  # xlsxwriter cuenta desde 0

    # ---------- Encabezados, anchos y formato de cada columna ----------
    for numero, (columna, nombre, formato) in enumerate(columnas):
        hoja.write(fila_encabezado, numero, nombre, estilo_encabezado)

        if formato == "fecha":
            largo = 11
        else:
            muestra = datos[columna].head(500).map(lambda v: len(str(v)) if not pd.isna(v) else 0)
            largo = int(muestra.max()) if len(muestra) else 0
            if formato in ("pesos", "entero", "decimal"):
                largo += 4  # separadores de miles y signo $

        hoja.set_column(numero, numero, min(max(largo, len(nombre)) + 3, 50), estilos[formato])

    hoja.set_row(fila_encabezado, 22)

    # ---------- Datos ----------
    for desplazamiento, (columna, _, formato) in enumerate(columnas):
        valores = datos[columna]

        for indice, valor in enumerate(valores.tolist(), start=fila_encabezado + 1):
            if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
                continue
            if formato == "fecha":
                hoja.write_datetime(indice, desplazamiento, valor.to_pydatetime(), estilos["fecha"])
            elif formato == "texto":
                hoja.write_string(indice, desplazamiento, valor)
            else:
                hoja.write_number(indice, desplazamiento, float(valor))

    ultima_fila = fila_encabezado + len(datos)

    # Encabezado fijo al bajar y filtros en cada columna
    hoja.freeze_panes(fila_encabezado + 1, 0)
    hoja.autofilter(fila_encabezado, 0, max(ultima_fila, fila_encabezado), len(columnas) - 1)

    libro.close()
    archivo.seek(0)
    return archivo
