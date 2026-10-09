from flask import Flask, render_template, request, jsonify
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

# Cargar la clave privada desde .env
load_dotenv()

app = Flask(__name__)

# Conexión con OpenAI
cliente_openai = OpenAI()


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
entregas_df = pd.read_csv("data/fact_entregas.csv")



# =========================
# DASHBOARD
# =========================

@app.route("/")
def inicio():

    # Indicadores generales
    total_pedidos = len(pedidos_df)
    total_vehiculos = len(vehiculos_df)
    total_conductores = len(conductores_df)
    total_rutas = len(rutas_df)

    # Estados de pedidos
    estados_pedidos = pedidos_df["estado_pedido"].value_counts().to_dict()
    estados_pedidos_labels = list(estados_pedidos.keys())
    estados_pedidos_valores = list(estados_pedidos.values())

    # Estados de vehículos
    estados_vehiculos = vehiculos_df["estado"].value_counts().to_dict()
    estados_vehiculos_labels = list(estados_vehiculos.keys())
    estados_vehiculos_valores = list(estados_vehiculos.values())

    # Vehículos disponibles
    vehiculos_disponibles = int(
        (vehiculos_df["estado"] == "Disponible").sum()
    )

    # Conductores activos
    conductores_activos = int(
        (conductores_df["estado"] == "Activo").sum()
    )

    # Entregas realizadas a tiempo
    entregas = entregas_df.copy()

    entregas["a_tiempo"] = (
        entregas["entrega_a_tiempo"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "si", "sí", "yes", "a tiempo"])
    )

    total_entregas = len(entregas)

    entregas_a_tiempo = int(entregas["a_tiempo"].sum())

    porcentaje_a_tiempo = (
        round(entregas_a_tiempo / total_entregas * 100, 1)
        if total_entregas > 0 else 0
    )

    # Costos operacionales
    gasto_combustible = float(combustible_df["costo_total"].sum())
    costo_mantenciones = float(mantenciones_df["costo"].sum())
    costo_incidentes = float(incidentes_df["costo_estimado"].sum())

    costo_operacional = (
        gasto_combustible
        + costo_mantenciones
        + costo_incidentes
    )

    return render_template(
        "dashboard.html",
        total_pedidos=total_pedidos,
        total_vehiculos=total_vehiculos,
        total_conductores=total_conductores,
        total_rutas=total_rutas,
        estados_pedidos=estados_pedidos,
        estados_vehiculos=estados_vehiculos,
        estados_pedidos_labels=estados_pedidos_labels,
        estados_pedidos_valores=estados_pedidos_valores,
        estados_vehiculos_labels=estados_vehiculos_labels,
        estados_vehiculos_valores=estados_vehiculos_valores,
        vehiculos_disponibles=vehiculos_disponibles,
        conductores_activos=conductores_activos,
        total_entregas=total_entregas,
        entregas_a_tiempo=entregas_a_tiempo,
        porcentaje_a_tiempo=porcentaje_a_tiempo,
        gasto_combustible=gasto_combustible,
        costo_mantenciones=costo_mantenciones,
        costo_incidentes=costo_incidentes,
        costo_operacional=costo_operacional,
    )


# =========================
# PEDIDOS
# =========================

@app.route("/pedidos")
def pedidos():

    # =========================
    # FILTRO POR ESTADO
    # =========================

    estado_filtro = request.args.get(
        "estado",
        "Todos"
    )

    estados_validos = [
        "Todos",
        "Entregado",
        "En ruta"
    ]

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"


    # =========================
    # APLICAR FILTRO
    # =========================

    if estado_filtro == "Todos":

        pedidos_filtrados = pedidos_df.copy()

    else:

        pedidos_filtrados = pedidos_df[
            pedidos_df["estado_pedido"]
            == estado_filtro
        ].copy()


    # =========================
    # PAGINACIÓN
    # =========================

    pagina = request.args.get(
        "pagina",
        1,
        type=int
    )

    registros_por_pagina = 50

    total_registros = len(
        pedidos_filtrados
    )

    total_paginas = (
        total_registros
        + registros_por_pagina
        - 1
    ) // registros_por_pagina


    if total_paginas == 0:
        total_paginas = 1


    if pagina < 1:
        pagina = 1


    if pagina > total_paginas:
        pagina = total_paginas


    inicio = (
        pagina - 1
    ) * registros_por_pagina

    fin = (
        inicio
        + registros_por_pagina
    )


    # =========================
    # OBTENER PEDIDOS
    # =========================

    datos_pedidos = (
        pedidos_filtrados
        .iloc[inicio:fin]
        .copy()
    )


    # =========================
    # FORMATO DE FECHA
    # =========================

    datos_pedidos[
        "fecha_pedido_id"
    ] = (
        datos_pedidos[
            "fecha_pedido_id"
        ]
        .astype(str)
        .apply(
            lambda fecha:
                f"{fecha[6:8]}/"
                f"{fecha[4:6]}/"
                f"{fecha[0:4]}"
        )
    )


    # =========================
    # ESTADOS
    # =========================

    estados_pedidos = (
        pedidos_df[
            "estado_pedido"
        ]
        .value_counts()
        .to_dict()
    )


    # =========================
    # CONVERTIR A REGISTROS
    # =========================

    datos_pedidos = (
        datos_pedidos
        .to_dict(
            orient="records"
        )
    )


    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(

        "pedidos.html",

        pedidos=datos_pedidos,

        pagina=pagina,

        total_paginas=
            total_paginas,

        total_registros=
            total_registros,

        estados_pedidos=
            estados_pedidos,

        estado_filtro=
            estado_filtro,

        total_pedidos=
            len(pedidos_df)
    )


# =========================
# VEHÍCULOS
# =========================

@app.route("/vehiculos")
def vehiculos():

    # =========================
    # FILTRO POR ESTADO
    # =========================

    estado_filtro = request.args.get(
        "estado",
        "Todos"
    )

    estados_validos = [
        "Todos",
        "Disponible",
        "En ruta",
        "Mantención"
    ]

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"


    # =========================
    # APLICAR FILTRO
    # =========================

    if estado_filtro == "Todos":

        vehiculos_filtrados = (
            vehiculos_df.copy()
        )

    else:

        vehiculos_filtrados = (
            vehiculos_df[
                vehiculos_df["estado"]
                == estado_filtro
            ]
            .copy()
        )


    # =========================
    # PAGINACIÓN
    # =========================

    pagina = request.args.get(
        "pagina",
        1,
        type=int
    )

    registros_por_pagina = 50

    total_registros = len(
        vehiculos_filtrados
    )

    total_paginas = (
        total_registros
        + registros_por_pagina
        - 1
    ) // registros_por_pagina


    if total_paginas == 0:
        total_paginas = 1


    if pagina < 1:
        pagina = 1


    if pagina > total_paginas:
        pagina = total_paginas


    inicio = (
        pagina - 1
    ) * registros_por_pagina

    fin = (
        inicio
        + registros_por_pagina
    )


    # =========================
    # OBTENER VEHÍCULOS
    # =========================

    datos_vehiculos = (
        vehiculos_filtrados
        .iloc[inicio:fin]
        .copy()
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
    # CONVERTIR A REGISTROS
    # =========================

    datos_vehiculos = (
        datos_vehiculos
        .to_dict(
            orient="records"
        )
    )


    # =========================
    # ENVIAR DATOS
    # =========================

    return render_template(

        "vehiculos.html",

        vehiculos=datos_vehiculos,

        pagina=pagina,

        total_paginas=
            total_paginas,

        total_registros=
            total_registros,

        estados_vehiculos=
            estados_vehiculos,

        estado_filtro=
            estado_filtro,

        total_vehiculos=
            len(vehiculos_df)
    )


# =========================
# CONDUCTORES
# =========================

@app.route("/conductores")
def conductores():

    # =========================
    # FILTRO POR ESTADO
    # =========================

    estado_filtro = request.args.get("estado", "Todos")

    estados_validos = [
        "Todos",
        "Activo",
        "Inactivo",
        "Licencia médica",
        "Vacaciones"
    ]

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"


    # =========================
    # APLICAR FILTRO
    # =========================

    if estado_filtro == "Todos":
        conductores_filtrados = conductores_df.copy()
    else:
        conductores_filtrados = conductores_df[
            conductores_df["estado"] == estado_filtro
        ].copy()


    # =========================
    # CONFIGURACIÓN PAGINACIÓN
    # =========================

    pagina = request.args.get("pagina", 1, type=int)

    registros_por_pagina = 50

    total_registros = len(conductores_filtrados)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina


    # Evitar páginas inválidas

    if total_paginas == 0:
        total_paginas = 1

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas


    inicio = (pagina - 1) * registros_por_pagina
    fin = inicio + registros_por_pagina


    # =========================
    # OBTENER CONDUCTORES
    # =========================

    datos_conductores = conductores_filtrados.iloc[
        inicio:fin
    ].copy()


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
    # ENVIAR DATOS
    # =========================

    return render_template(
        "conductores.html",
        conductores=datos_conductores,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        total_conductores=len(conductores_df),
        estados_conductores=estados_conductores,
        estado_filtro=estado_filtro
    )


# =========================
# RUTAS
# =========================

@app.route("/rutas")
def rutas():

    # =========================
    # FILTRO POR ESTADO
    # =========================

    estado_filtro = request.args.get("estado", "Todos")

    estados_validos = [
        "Todos",
        "Activa",
        "Restringida",
        "Suspendida"
    ]

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"


    # =========================
    # APLICAR FILTRO
    # =========================

    if estado_filtro == "Todos":

        rutas_filtradas = rutas_df.copy()

    else:

        rutas_filtradas = rutas_df[
            rutas_df["estado"] == estado_filtro
        ].copy()


    # =========================
    # PAGINACIÓN
    # =========================

    pagina = request.args.get(
        "pagina",
        1,
        type=int
    )

    registros_por_pagina = 50

    total_registros = len(rutas_filtradas)

    total_paginas = (
        total_registros + registros_por_pagina - 1
    ) // registros_por_pagina


    if total_paginas == 0:
        total_paginas = 1


    if pagina < 1:
        pagina = 1


    if pagina > total_paginas:
        pagina = total_paginas


    inicio = (
        pagina - 1
    ) * registros_por_pagina

    fin = inicio + registros_por_pagina


    # =========================
    # DATOS DE LA PÁGINA
    # =========================

    datos_rutas = rutas_filtradas.iloc[
        inicio:fin
    ].copy()


    datos_rutas = datos_rutas.to_dict(
        orient="records"
    )


    # =========================
    # ESTADOS
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
        total_rutas=len(rutas_df),
        estados_rutas=estados_rutas,
        estado_filtro=estado_filtro
    )

# =========================
# MANTENCIONES
# =========================

@app.route("/mantenciones")
def mantenciones():

    pagina = request.args.get("pagina", 1, type=int)

    por_pagina = 50

    total_registros = len(mantenciones_df)

    total_paginas = (
        (total_registros + por_pagina - 1)
        // por_pagina
    )

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * por_pagina
    fin = inicio + por_pagina

    # Datos de la página actual
    datos_mantenciones = mantenciones_df.iloc[inicio:fin].copy()

    # Formatear fecha
    datos_mantenciones["fecha_mantencion_id"] = (
        datos_mantenciones["fecha_mantencion_id"]
        .astype(str)
        .str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
    )

    # Relacionar vehiculo_id con patente
    mapa_patentes = (
        vehiculos_df
        .set_index("vehiculo_id")["patente"]
        .to_dict()
    )

    datos_mantenciones["patente"] = (
        datos_mantenciones["vehiculo_id"]
        .map(mapa_patentes)
    )

    # Convertir NaN a texto vacío por seguridad
    datos_mantenciones["patente"] = (
        datos_mantenciones["patente"]
        .fillna("")
    )

    mantenciones = datos_mantenciones.to_dict("records")

    # Vehículos únicos con mantenciones
    vehiculos_mantencion = (
        mantenciones_df["vehiculo_id"]
        .nunique()
    )

    # Costo total
    costo_total = (
        mantenciones_df["costo"]
        .sum()
    )

    return render_template(
        "mantenciones.html",
        mantenciones=mantenciones,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        vehiculos_mantencion=vehiculos_mantencion,
        costo_total=costo_total
    )


# =========================
# COMBUSTIBLE
# =========================

@app.route("/combustible")
def combustible():

    pagina = request.args.get("pagina", 1, type=int)

    por_pagina = 50

    total_registros = len(combustible_df)

    total_paginas = (
        (total_registros + por_pagina - 1)
        // por_pagina
    )

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * por_pagina
    fin = inicio + por_pagina

    # Datos de la página actual
    datos_combustible = combustible_df.iloc[inicio:fin].copy()

    # Formatear fecha
    datos_combustible["fecha_id"] = (
        datos_combustible["fecha_id"]
        .astype(str)
        .str.replace(
            r"(\d{4})(\d{2})(\d{2})",
            r"\1-\2-\3",
            regex=True
        )
    )

    # Relacionar vehiculo_id con patente
    mapa_patentes = (
        vehiculos_df
        .set_index("vehiculo_id")["patente"]
        .to_dict()
    )

    datos_combustible["patente"] = (
        datos_combustible["vehiculo_id"]
        .map(mapa_patentes)
    )

    # Seguridad por si algún vehículo no tiene coincidencia
    datos_combustible["patente"] = (
        datos_combustible["patente"]
        .fillna("")
    )

    combustible = datos_combustible.to_dict("records")

    # Vehículos registrados
    vehiculos_registrados = (
        combustible_df["vehiculo_id"]
        .nunique()
    )

    # Gasto total
    gasto_total = (
        combustible_df["costo_total"]
        .sum()
    )

    return render_template(
        "combustible.html",
        combustible=combustible,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        vehiculos_registrados=vehiculos_registrados,
        gasto_total=gasto_total
    )

# =========================
# INCIDENTES
# =========================

@app.route("/incidentes")
def incidentes():

    pagina = request.args.get("pagina", 1, type=int)

    estado_filtro = request.args.get("estado", "Todos")

    estados_validos = [
        "Todos",
        "Abierto",
        "Resuelto"
    ]

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"

    por_pagina = 50

    # Crear una copia para trabajar con el estado
    incidentes_base = incidentes_df.copy()

    # Convertir resuelto a estado visible
    incidentes_base["estado_incidente"] = (
        incidentes_base["resuelto"]
        .astype(str)
        .str.lower()
        .map({
            "true": "Resuelto",
            "1": "Resuelto",
            "si": "Resuelto",
            "sí": "Resuelto",
            "false": "Abierto",
            "0": "Abierto",
            "no": "Abierto"
        })
        .fillna("Abierto")
    )

    # Contadores generales
    incidentes_abiertos = (
        incidentes_base["estado_incidente"]
        .eq("Abierto")
        .sum()
    )

    incidentes_resueltos = (
        incidentes_base["estado_incidente"]
        .eq("Resuelto")
        .sum()
    )

    # Aplicar filtro de tarjeta
    if estado_filtro != "Todos":

        incidentes_filtrados = incidentes_base[
            incidentes_base["estado_incidente"] == estado_filtro
        ].copy()

    else:

        incidentes_filtrados = incidentes_base.copy()

    # Total según filtro
    total_registros = len(incidentes_filtrados)

    # Paginación
    total_paginas = max(
        1,
        (total_registros + por_pagina - 1) // por_pagina
    )

    if pagina < 1:
        pagina = 1

    if pagina > total_paginas:
        pagina = total_paginas

    inicio = (pagina - 1) * por_pagina
    fin = inicio + por_pagina

    datos_incidentes = incidentes_filtrados.iloc[inicio:fin].copy()

    # Formatear fecha
    datos_incidentes["fecha_incidente_id"] = (
        datos_incidentes["fecha_incidente_id"]
        .astype(str)
        .str.replace(
            r"(\d{4})(\d{2})(\d{2})",
            r"\1-\2-\3",
            regex=True
        )
    )

    # Relacionar vehiculo_id con patente
    mapa_patentes = (
        vehiculos_df
        .set_index("vehiculo_id")["patente"]
        .to_dict()
    )

    datos_incidentes["patente"] = (
        datos_incidentes["vehiculo_id"]
        .map(mapa_patentes)
        .fillna("")
    )

    incidentes = datos_incidentes.to_dict("records")

    return render_template(
        "incidentes.html",
        incidentes=incidentes,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        incidentes_abiertos=incidentes_abiertos,
        incidentes_resueltos=incidentes_resueltos,
        estado_filtro=estado_filtro
    )

    # =========================
    # CONVERTIR ESTADO
    # =========================

    def convertir_resuelto(valor):

        texto = (
            str(valor)
            .strip()
            .lower()
        )

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


    datos_incidentes[
        "estado_incidente"
    ] = (
        datos_incidentes[
            "resuelto"
        ]
        .apply(
            convertir_resuelto
        )
    )


    datos_incidentes = (
        datos_incidentes
        .to_dict(
            orient="records"
        )
    )


    estados = (
        incidentes_df["resuelto"]
        .apply(
            convertir_resuelto
        )
    )


    incidentes_resueltos = (
        estados == "Resuelto"
    ).sum()


    incidentes_abiertos = (
        estados == "Abierto"
    ).sum()


    costo_total = (
        incidentes_df[
            "costo_estimado"
        ]
        .sum()
    )


    return render_template(

        "incidentes.html",

        incidentes=
            datos_incidentes,

        pagina=pagina,

        total_paginas=
            total_paginas,

        total_registros=
            total_registros,

        incidentes_resueltos=
            incidentes_resueltos,

        incidentes_abiertos=
            incidentes_abiertos,

        costo_total=
            costo_total
    )


# =========================
# EJECUTAR APLICACIÓN
# =========================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )