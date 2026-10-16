"""Filtro por rango de fechas (?desde=AAAA-MM-DD&hasta=AAAA-MM-DD).

Las fechas de los CSV vienen como número AAAAMMDD (ej. 20250108),
así que comparar números enteros basta para filtrar.
"""

from datetime import date, timedelta


def leer_fecha(texto):
    """"2026-10-01" -> date, o None si viene vacío o mal escrito."""
    try:
        return date.fromisoformat(str(texto or "").strip())
    except ValueError:
        return None


def leer_rango(argumentos):
    """Lee desde/hasta de la URL. Si vienen al revés, los ordena."""

    desde = leer_fecha(argumentos.get("desde"))
    hasta = leer_fecha(argumentos.get("hasta"))

    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde

    return desde, hasta


def a_numero(fecha):
    """date(2026, 10, 1) -> 20261001"""
    return fecha.year * 10000 + fecha.month * 100 + fecha.day


def filtrar_por_fecha(df, columna, desde, hasta):
    """Filas cuya columna AAAAMMDD está dentro del rango (incluye ambos extremos)."""

    if desde:
        df = df[df[columna] >= a_numero(desde)]
    if hasta:
        df = df[df[columna] <= a_numero(hasta)]
    return df


def _fin_de_mes(fecha):
    siguiente = (fecha.replace(day=28) + timedelta(days=4)).replace(day=1)
    return siguiente - timedelta(days=1)


def _restar_meses(fecha, meses):
    """Primer día del mes que está `meses` meses antes."""
    total = fecha.year * 12 + (fecha.month - 1) - meses
    return date(total // 12, total % 12 + 1, 1)


def atajos(hoy):
    """Rangos rápidos, calculados según la fecha de hoy."""

    inicio_mes = hoy.replace(day=1)
    mes_anterior = _restar_meses(hoy, 1)

    return [
        {"clave": "todo", "nombre": "Todo", "desde": None, "hasta": None},
        {"clave": "mes", "nombre": "Este mes", "desde": inicio_mes, "hasta": _fin_de_mes(hoy)},
        {"clave": "mes_anterior", "nombre": "Mes anterior", "desde": mes_anterior, "hasta": _fin_de_mes(mes_anterior)},
        {"clave": "3_meses", "nombre": "Últimos 3 meses", "desde": _restar_meses(hoy, 2), "hasta": _fin_de_mes(hoy)},
        {"clave": "anio", "nombre": "Este año", "desde": date(hoy.year, 1, 1), "hasta": date(hoy.year, 12, 31)},
        {"clave": "anio_anterior", "nombre": "Año anterior", "desde": date(hoy.year - 1, 1, 1), "hasta": date(hoy.year - 1, 12, 31)},
    ]


def formato_corto(fecha):
    return fecha.strftime("%d-%m-%Y")


def describir(desde, hasta):
    """Texto del período, ej. "del 01-10-2026 al 31-10-2026"."""

    if desde and hasta:
        return f"del {formato_corto(desde)} al {formato_corto(hasta)}"
    if desde:
        return f"desde el {formato_corto(desde)}"
    if hasta:
        return f"hasta el {formato_corto(hasta)}"
    return "todo el período"


def contexto(desde, hasta, hoy, minimo=None, maximo=None):
    """Datos que necesita el componente de filtro en la página."""

    lista = []
    for atajo in atajos(hoy):
        atajo = dict(atajo)
        atajo["activo"] = (atajo["desde"], atajo["hasta"]) == (desde, hasta)
        atajo["args"] = {
            clave: valor.isoformat()
            for clave, valor in (("desde", atajo["desde"]), ("hasta", atajo["hasta"]))
            if valor
        }
        lista.append(atajo)

    return {
        "desde": desde.isoformat() if desde else "",
        "hasta": hasta.isoformat() if hasta else "",
        "hay_filtro": bool(desde or hasta),
        "personalizado": bool(desde or hasta) and not any(a["activo"] for a in lista),
        "descripcion": describir(desde, hasta),
        "atajos": lista,
        "minimo": minimo.isoformat() if minimo else "",
        "maximo": maximo.isoformat() if maximo else "",
    }


def args_url(desde, hasta, **otros):
    """Parámetros para url_for que mantienen el filtro (sin los vacíos)."""

    args = {clave: valor for clave, valor in otros.items() if valor and valor != "Todos"}
    if desde:
        args["desde"] = desde.isoformat()
    if hasta:
        args["hasta"] = hasta.isoformat()
    return args
