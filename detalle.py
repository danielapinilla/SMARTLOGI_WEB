"""Cálculos para las páginas de detalle de un conductor y de un vehículo."""

import pandas as pd

MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

VALORES_SI = {"sí", "si", "true", "1", "yes"}


def _a_tiempo(serie):
    return serie.astype(str).str.strip().str.lower().isin(VALORES_SI)


def _fecha(fecha_id):
    """20250108 -> 08-01-2025"""
    texto = str(int(fecha_id))
    return f"{texto[6:8]}-{texto[4:6]}-{texto[0:4]}"


def _etiqueta_mes(clave):
    """202501 -> "Ene 2025" """
    clave = int(clave)
    return f"{MESES_CORTOS[clave % 100 - 1]} {clave // 100}"


def _meses_entre(minimo, maximo):
    """Lista de claves AAAAMM desde minimo hasta maximo (incluidos)."""
    meses = []
    anio, mes = divmod(int(minimo), 100)
    while anio * 100 + mes <= int(maximo):
        meses.append(anio * 100 + mes)
        mes += 1
        if mes > 12:
            anio, mes = anio + 1, 1
    return meses


# =========================
# CONDUCTOR
# =========================

def detalle_conductor(conductor_id, conductores, entregas, incidentes, rutas, vehiculos):
    """Devuelve un dict con todo lo que muestra la página, o None si no existe."""

    fila = conductores[conductores["conductor_id"] == conductor_id]
    if fila.empty:
        return None

    info = fila.iloc[0].to_dict()

    nombre_ruta = rutas.set_index("ruta_id")["nombre_ruta"]
    patente = vehiculos.set_index("vehiculo_id")["patente"]

    # ---------- Entregas ----------
    propias = entregas[entregas["conductor_id"] == conductor_id].copy()
    propias["a_tiempo"] = _a_tiempo(propias["entrega_a_tiempo"])

    total = len(propias)
    a_tiempo = int(propias["a_tiempo"].sum())
    puntualidad = round(a_tiempo / total * 100, 1) if total else None

    todas = entregas.assign(a_tiempo=_a_tiempo(entregas["entrega_a_tiempo"]))
    puntualidad_general = round(todas["a_tiempo"].mean() * 100, 1) if len(todas) else 0
    retraso_general = round(float(todas["retraso_min"].mean()), 1) if len(todas) else 0

    # Puesto en el ranking de puntualidad (entre conductores con entregas)
    ranking = todas.groupby("conductor_id")["a_tiempo"].mean().sort_values(ascending=False)
    puesto = (int(ranking.index.get_loc(conductor_id)) + 1) if conductor_id in ranking.index else None

    # Entregas por mes (todos los meses del período, aunque tengan 0)
    por_mes_labels, por_mes_valores = [], []
    if len(entregas):
        meses = _meses_entre(entregas["fecha_salida_id"].min() // 100, entregas["fecha_salida_id"].max() // 100)
        conteo = (propias["fecha_salida_id"] // 100).value_counts()
        por_mes_labels = [_etiqueta_mes(m) for m in meses]
        por_mes_valores = [int(conteo.get(m, 0)) for m in meses]

    rutas_frecuentes = [
        {"nombre": nombre_ruta.get(ruta, f"Ruta {ruta}"), "ruta_id": int(ruta), "cantidad": int(cantidad)}
        for ruta, cantidad in propias["ruta_id"].value_counts().head(5).items()
    ]

    vehiculos_frecuentes = [
        {"patente": patente.get(vehiculo, str(vehiculo)), "vehiculo_id": int(vehiculo), "cantidad": int(cantidad)}
        for vehiculo, cantidad in propias["vehiculo_id"].value_counts().head(3).items()
    ]

    ultimas = propias.sort_values(["fecha_salida_id", "hora_salida"], ascending=False).head(10)
    ultimas_entregas = [
        {
            "entrega_id": int(e.entrega_id),
            "fecha": _fecha(e.fecha_salida_id),
            "ruta": nombre_ruta.get(e.ruta_id, f"Ruta {e.ruta_id}"),
            "patente": patente.get(e.vehiculo_id, str(e.vehiculo_id)),
            "vehiculo_id": int(e.vehiculo_id),
            "tiempo_real": int(e.tiempo_real_min),
            "tiempo_estimado": int(e.tiempo_estimado_min),
            "retraso": int(e.retraso_min),
            "a_tiempo": bool(e.a_tiempo),
        }
        for e in ultimas.itertuples()
    ]

    # ---------- Incidentes ----------
    sus_incidentes = incidentes[incidentes["conductor_id"] == conductor_id]
    abiertos = int(sus_incidentes["estado_incidente"].eq("Abierto").sum()) if len(sus_incidentes) else 0

    lista_incidentes = [
        {
            "incidente_id": int(i.incidente_id),
            "fecha": _fecha(i.fecha_incidente_id),
            "tipo": i.tipo_incidente,
            "gravedad": i.gravedad,
            "patente": patente.get(i.vehiculo_id, str(i.vehiculo_id)),
            "vehiculo_id": int(i.vehiculo_id),
            "costo": int(i.costo_estimado),
            "estado": i.estado_incidente,
        }
        for i in sus_incidentes.sort_values("fecha_incidente_id", ascending=False).head(15).itertuples()
    ]

    return {
        "info": info,
        "total_entregas": total,
        "entregas_a_tiempo": a_tiempo,
        "puntualidad": puntualidad,
        "puntualidad_general": puntualidad_general,
        "puesto": puesto,
        "total_ranking": len(ranking),
        "retraso_promedio": round(float(propias["retraso_min"].mean()), 1) if total else None,
        "retraso_general": retraso_general,
        "total_incidentes": len(sus_incidentes),
        "incidentes_abiertos": abiertos,
        "tiempo_perdido": int(sus_incidentes["tiempo_perdido_min"].sum()) if len(sus_incidentes) else 0,
        "por_mes_labels": por_mes_labels,
        "por_mes_valores": por_mes_valores,
        "rutas_frecuentes": rutas_frecuentes,
        "vehiculos_frecuentes": vehiculos_frecuentes,
        "ultimas_entregas": ultimas_entregas,
        "incidentes": lista_incidentes,
    }


# =========================
# VEHÍCULO
# =========================

def detalle_vehiculo(vehiculo_id, vehiculos, entregas, mantenciones, combustible, incidentes, conductores):
    """Devuelve un dict con todo lo que muestra la página, o None si no existe."""

    fila = vehiculos[vehiculos["vehiculo_id"] == vehiculo_id]
    if fila.empty:
        return None

    info = fila.iloc[0].to_dict()
    nombre_conductor = conductores.set_index("conductor_id")["nombre_conductor"]

    sus_entregas = entregas[entregas["vehiculo_id"] == vehiculo_id]
    sus_mantenciones = mantenciones[mantenciones["vehiculo_id"] == vehiculo_id]
    sus_cargas = combustible[combustible["vehiculo_id"] == vehiculo_id]
    sus_incidentes = incidentes[incidentes["vehiculo_id"] == vehiculo_id]

    gasto_combustible = float(sus_cargas["costo_total"].sum())
    costo_mantenciones = float(sus_mantenciones["costo"].sum())
    costo_incidentes = float(sus_incidentes["costo_estimado"].sum())

    # Costos por mes (combustible y mantenciones), todos los meses del período
    fechas = pd.concat([combustible["fecha_id"], mantenciones["fecha_mantencion_id"]])
    meses = _meses_entre(fechas.min() // 100, fechas.max() // 100) if len(fechas) else []

    combustible_mes = sus_cargas.groupby(sus_cargas["fecha_id"] // 100)["costo_total"].sum()
    mantencion_mes = sus_mantenciones.groupby(sus_mantenciones["fecha_mantencion_id"] // 100)["costo"].sum()

    conductores_frecuentes = [
        {"nombre": nombre_conductor.get(c, str(c)), "conductor_id": int(c), "cantidad": int(n)}
        for c, n in sus_entregas["conductor_id"].value_counts().head(3).items()
    ]

    ultimas_mantenciones = [
        {
            "mantencion_id": int(m.mantencion_id),
            "fecha": _fecha(m.fecha_mantencion_id),
            "tipo": m.tipo_mantencion,
            "descripcion": m.descripcion,
            "taller": m.taller,
            "costo": int(m.costo),
            "dias": int(m.dias_fuera_servicio),
            "resultado": m.resultado,
        }
        for m in sus_mantenciones.sort_values("fecha_mantencion_id", ascending=False).head(10).itertuples()
    ]

    ultimas_cargas = [
        {
            "fecha": _fecha(c.fecha_id),
            "litros": float(c.litros_cargados),
            "precio_litro": int(c.precio_litro),
            "costo": int(c.costo_total),
            "kilometraje": int(c.kilometraje_actual),
            "estacion": c.estacion_carga,
        }
        for c in sus_cargas.sort_values("fecha_id", ascending=False).head(10).itertuples()
    ]

    lista_incidentes = [
        {
            "incidente_id": int(i.incidente_id),
            "fecha": _fecha(i.fecha_incidente_id),
            "tipo": i.tipo_incidente,
            "gravedad": i.gravedad,
            "conductor": nombre_conductor.get(i.conductor_id, str(i.conductor_id)),
            "conductor_id": int(i.conductor_id),
            "costo": int(i.costo_estimado),
            "estado": i.estado_incidente,
        }
        for i in sus_incidentes.sort_values("fecha_incidente_id", ascending=False).head(15).itertuples()
    ]

    return {
        "info": info,
        "total_entregas": len(sus_entregas),
        "gasto_combustible": gasto_combustible,
        "litros": float(sus_cargas["litros_cargados"].sum()),
        "total_cargas": len(sus_cargas),
        "costo_mantenciones": costo_mantenciones,
        "total_mantenciones": len(sus_mantenciones),
        "dias_fuera_servicio": int(sus_mantenciones["dias_fuera_servicio"].sum()),
        "costo_incidentes": costo_incidentes,
        "total_incidentes": len(sus_incidentes),
        "incidentes_abiertos": int(sus_incidentes["estado_incidente"].eq("Abierto").sum()),
        "costo_total": gasto_combustible + costo_mantenciones + costo_incidentes,
        "costos_mes_labels": [_etiqueta_mes(m) for m in meses],
        "costos_mes_combustible": [int(combustible_mes.get(m, 0)) for m in meses],
        "costos_mes_mantencion": [int(mantencion_mes.get(m, 0)) for m in meses],
        "conductores_frecuentes": conductores_frecuentes,
        "ultimas_mantenciones": ultimas_mantenciones,
        "ultimas_cargas": ultimas_cargas,
        "incidentes": lista_incidentes,
    }
