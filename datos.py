"""Datos de cada empresa.

- La "Empresa demo" usa los CSV de la carpeta data/ (los datos de ejemplo).
- Las empresas registradas leen sus datos desde Supabase, siempre filtrando
  por su empresa_id.

El resto de la app recibe un objeto Datos con las mismas tablas (DataFrames)
sin importar de dónde vinieron.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

import pandas as pd

CARPETA_DATOS = Path(__file__).resolve().parent / "data"

# nombre de la tabla -> (archivo CSV de la demo, columnas)
TABLAS = {
    "pedidos": ("fact_pedidos_10000.csv", [
        "pedido_id", "cliente_id", "fecha_pedido_id", "tipo_servicio", "cantidad_paquetes",
        "peso_total_kg", "prioridad", "valor_pedido", "comuna_entrega", "estado_pedido"]),
    "vehiculos": ("dim_vehiculos_30.csv", [
        "vehiculo_id", "patente", "tipo_vehiculo", "marca", "modelo", "anio",
        "capacidad_kg", "combustible", "fecha_alta", "estado"]),
    "conductores": ("dim_conductores_50.csv", [
        "conductor_id", "nombre_conductor", "fecha_ingreso", "experiencia_anios",
        "tipo_licencia", "estado"]),
    "rutas": ("dim_rutas_100.csv", [
        "ruta_id", "nombre_ruta", "comuna_origen", "comuna_destino", "distancia_km",
        "tiempo_estimado_min", "nivel_trafico_habitual", "tipo_ruta", "peajes", "estado"]),
    "clientes": ("dim_clientes_500.csv", [
        "cliente_id", "nombre_cliente", "tipo_cliente", "comuna", "ciudad",
        "fecha_registro", "segmento"]),
    "entregas": ("fact_entregas.csv", [
        "entrega_id", "pedido_id", "fecha_salida_id", "fecha_entrega_id", "conductor_id",
        "vehiculo_id", "ruta_id", "hora_salida", "hora_entrega", "tiempo_real_min",
        "tiempo_estimado_min", "retraso_min", "entrega_a_tiempo", "estado_entrega"]),
    "mantenciones": ("fact_mantenciones_1000.csv", [
        "mantencion_id", "vehiculo_id", "fecha_mantencion_id", "tipo_mantencion",
        "descripcion", "costo", "kilometraje", "dias_fuera_servicio", "taller", "resultado"]),
    "combustible": ("fact_combustible_3000.csv", [
        "combustible_id", "vehiculo_id", "fecha_id", "litros_cargados", "precio_litro",
        "costo_total", "kilometraje_actual", "tipo_combustible", "estacion_carga"]),
    "incidentes": ("fact_incidentes_500.csv", [
        "incidente_id", "entrega_id", "fecha_incidente_id", "vehiculo_id", "conductor_id",
        "tipo_incidente", "gravedad", "descripcion", "tiempo_perdido_min",
        "costo_estimado", "resuelto"]),
}

# Columnas numéricas (en una empresa sin datos, la tabla vacía igual debe
# tener números para que sumas y promedios funcionen)
NUMERICAS = {
    "pedido_id", "cliente_id", "fecha_pedido_id", "cantidad_paquetes", "peso_total_kg",
    "valor_pedido", "vehiculo_id", "anio", "capacidad_kg", "conductor_id",
    "experiencia_anios", "ruta_id", "distancia_km", "tiempo_estimado_min", "peajes",
    "entrega_id", "fecha_salida_id", "fecha_entrega_id", "tiempo_real_min", "retraso_min",
    "mantencion_id", "fecha_mantencion_id", "costo", "kilometraje", "dias_fuera_servicio",
    "combustible_id", "fecha_id", "litros_cargados", "precio_litro", "costo_total",
    "kilometraje_actual", "incidente_id", "fecha_incidente_id", "tiempo_perdido_min",
    "costo_estimado",
}

# Cuánto tiempo se reutilizan los datos de una empresa antes de volver a leerlos
SEGUNDOS_CACHE = 60


class Datos:
    """Las tablas de una empresa, listas para usar."""

    def __init__(self, clave, tablas):
        self.clave = clave  # identifica la empresa (para cachés)

        self.pedidos = tablas["pedidos"]
        self.vehiculos = tablas["vehiculos"]
        self.conductores = tablas["conductores"]
        self.rutas = tablas["rutas"]
        self.clientes = tablas["clientes"]
        self.entregas = tablas["entregas"]
        self.mantenciones = tablas["mantenciones"]
        self.combustible = tablas["combustible"]
        self.incidentes = tablas["incidentes"]

        # "resuelto" (Sí/No/En seguimiento) -> estado visible
        self.incidentes["estado_incidente"] = (
            self.incidentes["resuelto"].astype(str).str.strip().str.lower()
            .map({"true": "Resuelto", "1": "Resuelto", "si": "Resuelto", "sí": "Resuelto",
                  "false": "Abierto", "0": "Abierto", "no": "Abierto"})
            .fillna("Abierto")
        )

        self.mapa_patentes = self.vehiculos.set_index("vehiculo_id")["patente"].to_dict()

    @property
    def vacia(self):
        """True si la empresa todavía no cargó ningún dato."""
        return all(len(getattr(self, nombre)) == 0 for nombre in TABLAS)


def _ordenar(df, nombre):
    """Deja las columnas en el orden esperado y con el tipo correcto."""
    columnas = TABLAS[nombre][1]
    for columna in columnas:
        if columna not in df.columns:
            df[columna] = pd.Series(dtype="float64" if columna in NUMERICAS else "object")
    df = df[columnas].copy()
    for columna in columnas:
        if columna in NUMERICAS:
            df[columna] = pd.to_numeric(df[columna], errors="coerce")
    return df


# =========================
# EMPRESA DEMO (CSV)
# =========================

@lru_cache(maxsize=1)
def demo():
    tablas = {
        nombre: _ordenar(pd.read_csv(CARPETA_DATOS / archivo), nombre)
        for nombre, (archivo, _) in TABLAS.items()
    }
    return Datos("demo", tablas)


# =========================
# EMPRESAS REGISTRADAS (SUPABASE)
# =========================

def _supabase():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/").removesuffix("/rest/v1")
    clave = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return url, clave


def _leer_tabla(nombre, empresa_id):
    """Lee todas las filas de la empresa, de a 1.000 (límite de Supabase)."""

    url, clave = _supabase()
    columnas = ",".join(TABLAS[nombre][1])
    filas, desde = [], 0

    while True:
        consulta = urllib.parse.urlencode({
            "select": columnas,
            "empresa_id": f"eq.{empresa_id}",
            "limit": 1000,
            "offset": desde,
        })
        peticion = urllib.request.Request(
            f"{url}/rest/v1/{nombre}?{consulta}",
            headers={"apikey": clave, "Authorization": f"Bearer {clave}"},
        )
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            pagina = json.load(respuesta)

        filas.extend(pagina)
        if len(pagina) < 1000:
            break
        desde += 1000

    return _ordenar(pd.DataFrame(filas), nombre)


_cache = {}  # empresa_id -> (momento, Datos)


def de_empresa(empresa_id):
    """Datos de una empresa registrada (se reutilizan por SEGUNDOS_CACHE)."""

    guardado = _cache.get(empresa_id)
    if guardado and time.time() - guardado[0] < SEGUNDOS_CACHE:
        return guardado[1]

    tablas = {nombre: _leer_tabla(nombre, empresa_id) for nombre in TABLAS}
    datos = Datos(empresa_id, tablas)
    _cache[empresa_id] = (time.time(), datos)
    return datos


def olvidar(empresa_id):
    """Borra el caché de una empresa (ej. después de cargar datos nuevos)."""
    _cache.pop(empresa_id, None)
