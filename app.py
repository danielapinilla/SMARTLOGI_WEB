from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)

@app.template_filter("miles")
def formato_miles(valor):
    return f"{valor:,}".replace(",", ".")

# =========================
# CARGAR DATOS
# =========================

pedidos_df = pd.read_csv("data/fact_pedidos_10000.csv")
vehiculos_df = pd.read_csv("data/dim_vehiculos_30.csv")
conductores_df = pd.read_csv("data/dim_conductores_50.csv")
rutas_df = pd.read_csv("data/dim_rutas_100.csv")
mantenciones_df = pd.read_csv("data/fact_mantenciones_1000.csv")
combustible_df = pd.read_csv("data/fact_combustible_3000.csv")
incidentes_df = pd.read_csv("data/fact_incidentes_500.csv")


# =========================
# DASHBOARD
# =========================

@app.route("/")
def inicio():

    # Datos de pedidos
    total_pedidos = len(pedidos_df)
    estados_pedidos = pedidos_df["estado_pedido"].value_counts().to_dict()
    estados_pedidos_labels = list(estados_pedidos.keys())
    estados_pedidos_valores = list(estados_pedidos.values())

    # Datos de vehículos
    total_vehiculos = len(vehiculos_df)
    estados_vehiculos = vehiculos_df["estado"].value_counts().to_dict()

    estados_vehiculos_labels = list(estados_vehiculos.keys())
    estados_vehiculos_valores = list(estados_vehiculos.values())

    total_conductores = len(conductores_df)
    total_rutas = len(rutas_df)


    return render_template(
        "dashboard.html",
        total_pedidos=total_pedidos,
        estados_pedidos=estados_pedidos,
        total_vehiculos=total_vehiculos,
        estados_vehiculos=estados_vehiculos,
        total_conductores=total_conductores,
        total_rutas=total_rutas,
        estados_pedidos_labels=estados_pedidos_labels,
        estados_pedidos_valores=estados_pedidos_valores,
        estados_vehiculos_labels=estados_vehiculos_labels,
        estados_vehiculos_valores=estados_vehiculos_valores,
    )


# =========================
# MÓDULOS
# =========================

@app.route("/pedidos")
def pedidos():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(pedidos_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    # Evitar páginas inválidas
    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER PEDIDOS
    # =========================

    datos_pedidos = pedidos_df.iloc[inicio:fin].copy()

    # =========================
    # FORMATO DE FECHA
    # =========================

    datos_pedidos["fecha_pedido_id"] = (
        datos_pedidos["fecha_pedido_id"]
        .astype(str)
        .apply(
            lambda fecha: f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"
        )
    )

    # =========================
    # ESTADOS DE PEDIDOS
    # =========================

    estados_pedidos = (
        pedidos_df["estado_pedido"]
        .value_counts()
        .to_dict()
    )

    # =========================
    # CONVERTIR A REGISTROS
    # =========================

    datos_pedidos = datos_pedidos.to_dict(
        orient="records"
    )

    # =========================
    # ENVIAR DATOS A LA PÁGINA
    # =========================

    return render_template(
        "pedidos.html",
        pedidos=datos_pedidos,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        estados_pedidos=estados_pedidos
    )


@app.route("/vehiculos")
def vehiculos():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(vehiculos_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER VEHÍCULOS
    # =========================

    datos_vehiculos = vehiculos_df.iloc[inicio:fin].copy()

    datos_vehiculos = datos_vehiculos.to_dict(
        orient="records"
    )

    # =========================
    # ESTADOS DE VEHÍCULOS
    # =========================

    estados_vehiculos = (
        vehiculos_df["estado"]
        .value_counts()
        .to_dict()
    )

    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(
        "vehiculos.html",
        vehiculos=datos_vehiculos,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        estados_vehiculos=estados_vehiculos
    )

@app.route("/conductores")
def conductores():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(conductores_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER CONDUCTORES
    # =========================

    datos_conductores = conductores_df.iloc[inicio:fin].copy()

    datos_conductores = datos_conductores.to_dict(
        orient="records"
    )

    # =========================
    # ESTADOS
    # =========================

    estados_conductores = (
        conductores_df["estado"]
        .value_counts()
        .to_dict()
    )

    # =========================
    # ENVIAR DATOS A LA PÁGINA
    # =========================

    return render_template(
        "conductores.html",
        conductores=datos_conductores,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        estados_conductores=estados_conductores
    )


@app.route("/rutas")
def rutas():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(rutas_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    # Evitar páginas inválidas
    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER RUTAS
    # =========================

    datos_rutas = rutas_df.iloc[inicio:fin].copy()

    datos_rutas = datos_rutas.to_dict(
        orient="records"
    )

    # =========================
    # ESTADOS DE RUTAS
    # =========================

    estados_rutas = (
        rutas_df["estado"]
        .value_counts()
        .to_dict()
    )

    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(
        "rutas.html",
        rutas=datos_rutas,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        estados_rutas=estados_rutas
    )


@app.route("/mantenciones")
def mantenciones():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(mantenciones_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    # Evitar páginas inválidas
    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER MANTENCIONES
    # =========================

    datos_mantenciones = mantenciones_df.iloc[inicio:fin].copy()

    # =========================
    # FORMATO DE FECHA
    # =========================

    datos_mantenciones["fecha_mantencion_id"] = (
        datos_mantenciones["fecha_mantencion_id"]
        .astype(str)
        .apply(
            lambda fecha: (
                f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"
                if len(fecha) == 8
                else fecha
            )
        )
    )

    # =========================
    # CONVERTIR A REGISTROS
    # =========================

    datos_mantenciones = datos_mantenciones.to_dict(
        orient="records"
    )

    # =========================
    # DATOS RESUMEN
    # =========================

    vehiculos_mantencion = (
        mantenciones_df["vehiculo_id"]
        .nunique()
    )

    costo_total = (
        mantenciones_df["costo"]
        .sum()
    )

    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(
        "mantenciones.html",
        mantenciones=datos_mantenciones,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        vehiculos_mantencion=vehiculos_mantencion,
        costo_total=costo_total
    )


@app.route("/combustible")
def combustible():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(combustible_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    # Evitar páginas inválidas
    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # OBTENER REGISTROS
    # =========================

    datos_combustible = combustible_df.iloc[inicio:fin].copy()

    # =========================
    # FORMATO DE FECHA
    # =========================

    datos_combustible["fecha_id"] = (
        datos_combustible["fecha_id"]
        .astype(str)
        .apply(
            lambda fecha: (
                f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"
                if len(fecha) == 8
                else fecha
            )
        )
    )

    # =========================
    # CONVERTIR A REGISTROS
    # =========================

    datos_combustible = datos_combustible.to_dict(
        orient="records"
    )

    # =========================
    # DATOS RESUMEN
    # =========================

    vehiculos_registrados = (
        combustible_df["vehiculo_id"]
        .nunique()
    )

    gasto_total = (
        combustible_df["costo_total"]
        .sum()
    )

    litros_totales = (
        combustible_df["litros_cargados"]
        .sum()
    )

    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(
        "combustible.html",
        combustible=datos_combustible,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        vehiculos_registrados=vehiculos_registrados,
        gasto_total=gasto_total,
        litros_totales=litros_totales
    )


@app.route("/incidentes")
def incidentes():

    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(incidentes_df)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina

    # Evitar páginas inválidas
    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina

    # =========================
    # COPIAR DATOS
    # =========================

    datos_incidentes = incidentes_df.iloc[inicio:fin].copy()

    # =========================
    # FORMATO DE FECHA
    # =========================

    datos_incidentes["fecha_incidente_id"] = (
        datos_incidentes["fecha_incidente_id"]
        .astype(str)
        .apply(
            lambda fecha: (
                f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"
                if len(fecha) == 8
                else fecha
            )
        )
    )

    # =========================
    # FORMATO DE ESTADO
    # =========================

    def convertir_resuelto(valor):

        texto = str(valor).strip().lower()

        if texto in [
            "true",
            "1",
            "si",
            "sí",
            "yes",
            "resuelto",
            "cerrado"
        ]:
            return "Resuelto"

        return "Abierto"

    datos_incidentes["estado_incidente"] = (
        datos_incidentes["resuelto"]
        .apply(convertir_resuelto)
    )

    # =========================
    # CONVERTIR A REGISTROS
    # =========================

    datos_incidentes = datos_incidentes.to_dict(
        orient="records"
    )

    # =========================
    # RESUMEN
    # =========================

    estados = incidentes_df["resuelto"].apply(
        convertir_resuelto
    )

    incidentes_resueltos = (
        estados == "Resuelto"
    ).sum()

    incidentes_abiertos = (
        estados == "Abierto"
    ).sum()

    # =========================
    # COSTO TOTAL
    # =========================

    costo_total = incidentes_df[
        "costo_estimado"
    ].sum()

    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(
        "incidentes.html",
        incidentes=datos_incidentes,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        incidentes_resueltos=incidentes_resueltos,
        incidentes_abiertos=incidentes_abiertos,
        costo_total=costo_total
    )


# =========================
# EJECUTAR APLICACIÓN
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)