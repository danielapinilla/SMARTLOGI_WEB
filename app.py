import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from functools import lru_cache

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

import cuentas
import datos as fuente
import detalle
import fechas
from asistente import Asistente, construir_tablas, configuracion_ia
from exportar import crear_excel, nombre_archivo

# Cargar variables privadas desde .env (en Vercel se configuran en el panel)
load_dotenv()

app = Flask(__name__)

# Vercel atiende con https por delante; así url_for(_external=True) genera https://
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


# =========================
# CONFIGURACIÓN
# =========================

# Clave para firmar la sesión. En producción SIEMPRE debe venir de SECRET_KEY.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
)

# Acepta la URL aunque se pegue con /rest/v1/ al final
SUPABASE_URL = (
    os.environ.get("SUPABASE_URL", "")
    .strip()
    .rstrip("/")
    .removesuffix("/rest/v1")
)
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

REGISTROS_POR_PAGINA = 50

# Filtro por estado de cada sección: (columna, estados que se pueden elegir).
# Lo usan las páginas y la exportación a Excel, así siempre coinciden.
FILTROS_ESTADO = {
    "pedidos": ("estado_pedido", ["Todos", "Entregado", "En ruta", "En preparación", "Pendiente", "Cancelado"]),
    "vehiculos": ("estado", ["Todos", "Disponible", "En ruta", "Mantención", "Fuera de servicio"]),
    "conductores": ("estado", ["Todos", "Activo", "Inactivo", "Licencia médica", "Vacaciones"]),
    "rutas": ("estado", ["Todos", "Activa", "Restringida", "Suspendida"]),
    "incidentes": ("estado_incidente", ["Todos", "Abierto", "Resuelto"]),
}

# Columna de fecha (AAAAMMDD) de las secciones que se pueden filtrar por fecha.
COLUMNAS_FECHA = {
    "pedidos": "fecha_pedido_id",
    "mantenciones": "fecha_mantencion_id",
    "combustible": "fecha_id",
    "incidentes": "fecha_incidente_id",
}


@app.template_filter("miles")
def formato_miles(valor):
    return f"{valor:,}".replace(",", ".")


@app.template_filter("pesos")
def formato_pesos(valor):
    """250280365.0 -> $250.280.365"""
    return "$" + f"{round(valor or 0):,}".replace(",", ".")


@app.template_filter("porcentaje")
def formato_porcentaje(valor, decimales=1):
    """12.94 -> 12,9%"""
    return f"{valor:.{decimales}f}".replace(".", ",") + "%"


# =========================
# DATOS DE LA EMPRESA
# =========================

NOMBRE_DEMO = "Empresa demo"


def datos_actuales():
    """Datos de la empresa de quien inició sesión (o de la demo).

    Se guardan en `g` para leerlos una sola vez por visita a una página.
    """

    if "datos" not in g:
        empresa_id = session.get("empresa_id")
        g.datos = fuente.de_empresa(empresa_id) if empresa_id else fuente.demo()

    return g.datos


@app.context_processor
def datos_de_sesion():
    """Disponible en todas las plantillas."""
    return {
        "empresa_nombre": session.get("empresa") or NOMBRE_DEMO,
        "es_demo": not session.get("empresa_id"),
        "es_visitante": bool(session.get("visitante")),
    }


# =========================
# FUNCIONES DE APOYO
# =========================

def paginar(df):
    """Devuelve (filas de la página, página actual, total de páginas)."""

    pagina = request.args.get("pagina", 1, type=int)

    total_paginas = max(
        1,
        (len(df) + REGISTROS_POR_PAGINA - 1) // REGISTROS_POR_PAGINA
    )

    pagina = min(max(pagina, 1), total_paginas)

    inicio = (pagina - 1) * REGISTROS_POR_PAGINA
    fin = inicio + REGISTROS_POR_PAGINA

    return df.iloc[inicio:fin].copy(), pagina, total_paginas


def filtrar_por_estado(df, columna, estados_validos):
    """Lee ?estado= y devuelve (df filtrado, estado aplicado)."""

    estado_filtro = request.args.get("estado", "Todos")

    if estado_filtro not in estados_validos:
        estado_filtro = "Todos"

    if estado_filtro == "Todos":
        return df.copy(), estado_filtro

    return df[df[columna] == estado_filtro].copy(), estado_filtro


def filtro_de_fechas(df, columna, **otros_args):
    """Aplica ?desde=&hasta= a df y prepara lo que necesita la página.

    Devuelve (df filtrado, contexto para el componente, args para url_for).
    """

    desde, hasta = fechas.leer_rango(request.args)
    filtrado = fechas.filtrar_por_fecha(df, columna, desde, hasta)

    def _a_fecha(numero):
        return fechas.leer_fecha(f"{numero // 10000:04d}-{numero // 100 % 100:02d}-{numero % 100:02d}")

    contexto = fechas.contexto(
        desde, hasta, hora_chile().date(),
        minimo=_a_fecha(int(df[columna].min())) if len(df) else None,
        maximo=_a_fecha(int(df[columna].max())) if len(df) else None,
    )

    return filtrado, contexto, fechas.args_url(desde, hasta, **otros_args)


def fecha_guiones(serie):
    """20250108 -> 2025-01-08"""
    return serie.astype(str).str.replace(
        r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True
    )


# =========================
# INICIO DE SESIÓN (SUPABASE)
# =========================

LARGO_MINIMO_CLAVE = 8


def llamar_supabase(metodo, ruta, datos, token=None):
    """Llama a la API de Supabase Auth.

    Devuelve (respuesta_json, mensaje_error). Uno de los dos es None.
    """

    encabezados = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }

    if token:
        encabezados["Authorization"] = f"Bearer {token}"

    peticion = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/{ruta}",
        data=json.dumps(datos).encode(),
        headers=encabezados,
        method=metodo,
    )

    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return json.load(respuesta), None

    except urllib.error.HTTPError as error:
        try:
            detalle = json.load(error)
        except ValueError:
            detalle = {}

        return None, (
            detalle.get("msg")
            or detalle.get("error_description")
            or detalle.get("message")
            or f"Error {error.code}"
        )

    except (urllib.error.URLError, TimeoutError):
        return None, "No se pudo conectar con el servidor de acceso. Intenta de nuevo."


def supabase_configurado():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def destino_seguro(destino):
    """Evita redirigir a otros sitios después del login."""

    if destino and destino.startswith("/") and not destino.startswith("//"):
        return destino

    return url_for("inicio")


# Páginas que se pueden ver sin haber iniciado sesión
PAGINAS_PUBLICAS = {"login", "registro", "entrar_demo", "recuperar_clave", "nueva_clave", "static"}


@app.before_request
def exigir_sesion():

    if request.endpoint in PAGINAS_PUBLICAS:
        return None

    if not session.get("usuario"):
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    return None


@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("usuario"):
        return redirect(url_for("inicio"))

    error = None
    correo = ""

    if not supabase_configurado():
        error = "Falta configurar SUPABASE_URL y SUPABASE_ANON_KEY."

    elif request.method == "POST":

        correo = request.form.get("correo", "").strip().lower()
        clave = request.form.get("clave", "")

        if not correo or not clave:
            error = "Ingresa tu correo y tu clave."

        else:
            respuesta, error = llamar_supabase(
                "POST",
                "token?grant_type=password",
                {"email": correo, "password": clave},
            )

            if respuesta:
                usuario = respuesta.get("user") or {}

                # ¿A qué empresa pertenece? (sin empresa = ve la demo)
                miembro = None
                if cuentas.configurado():
                    try:
                        miembro = cuentas.empresa_de_usuario(usuario.get("id"))
                    except cuentas.ErrorCuenta:
                        app.logger.exception("No se pudo leer la empresa del usuario")

                iniciar_sesion(usuario.get("email", correo), miembro)
                return redirect(destino_seguro(request.args.get("next")))

            # No mostrar el detalle técnico de Supabase al usuario
            if not error.startswith("No se pudo conectar"):
                error = "Correo o clave incorrectos."

    return render_template("login.html", error=error, correo=correo)


def iniciar_sesion(correo, miembro=None, visitante=False):
    """Guarda en la sesión quién entró y a qué empresa pertenece."""

    session.clear()
    session.permanent = True
    session["usuario"] = correo

    if miembro:
        session["empresa_id"] = miembro["empresa_id"]
        session["empresa"] = miembro["empresa"]

    if visitante:
        session["visitante"] = True


@app.route("/registro", methods=["GET", "POST"])
def registro():
    """Crear la cuenta de una empresa nueva (con sus datos separados)."""

    if session.get("usuario") and not session.get("visitante"):
        return redirect(url_for("inicio"))

    error = None
    formulario = {"empresa": "", "nombre": "", "correo": ""}

    if not cuentas.configurado():
        error = "El registro todavía no está habilitado (falta SUPABASE_SERVICE_KEY)."

    elif request.method == "POST":

        formulario = {
            "empresa": request.form.get("empresa", "").strip(),
            "nombre": request.form.get("nombre", "").strip(),
            "correo": request.form.get("correo", "").strip().lower(),
        }
        clave = request.form.get("clave", "")
        confirmacion = request.form.get("confirmacion", "")

        if not all(formulario.values()) or not clave:
            error = "Completa todos los campos."

        elif len(formulario["empresa"]) > 80 or len(formulario["nombre"]) > 80:
            error = "El nombre de la empresa y tu nombre pueden tener hasta 80 caracteres."

        elif "@" not in formulario["correo"]:
            error = "Escribe un correo válido."

        elif len(clave) < LARGO_MINIMO_CLAVE:
            error = f"La clave debe tener al menos {LARGO_MINIMO_CLAVE} caracteres."

        elif clave != confirmacion:
            error = "Las claves no coinciden."

        else:
            try:
                _, empresa_id = cuentas.registrar_empresa(
                    formulario["empresa"], formulario["nombre"], formulario["correo"], clave
                )
            except cuentas.ErrorCuenta as problema:
                error = str(problema)
            else:
                iniciar_sesion(formulario["correo"], {
                    "empresa_id": empresa_id,
                    "empresa": formulario["empresa"],
                })
                flash(f"¡Bienvenida/o! La cuenta de {formulario['empresa']} quedó creada.")
                return redirect(url_for("inicio"))

    return render_template(
        "registro.html", error=error, formulario=formulario, largo_minimo=LARGO_MINIMO_CLAVE
    )


@app.route("/demo", methods=["POST"])
def entrar_demo():
    """Entrar a ver la Empresa demo sin crear cuenta."""
    iniciar_sesion("Visitante", visitante=True)
    return redirect(url_for("inicio"))


@app.route("/recuperar-clave", methods=["GET", "POST"])
def recuperar_clave():

    error = None
    enviado = False
    correo = ""

    if not supabase_configurado():
        error = "Falta configurar SUPABASE_URL y SUPABASE_ANON_KEY."

    elif request.method == "POST":

        correo = request.form.get("correo", "").strip().lower()

        if not correo:
            error = "Ingresa tu correo."

        else:
            # El mensaje es el mismo exista o no la cuenta:
            # así nadie puede averiguar qué correos están registrados.
            destino = url_for("nueva_clave", _external=True)
            _, error_envio = llamar_supabase(
                "POST",
                "recover?redirect_to=" + urllib.parse.quote(destino, safe=""),
                {"email": correo},
            )

            if error_envio:
                app.logger.warning("No se pudo enviar recuperación: %s", error_envio)

            enviado = True

    return render_template(
        "recuperar_clave.html", error=error, enviado=enviado, correo=correo
    )


@app.route("/nueva-clave", methods=["GET", "POST"])
def nueva_clave():
    """Página a la que llega el enlace del correo de Supabase.

    Supabase agrega el token después de "#" en la URL. El navegador lo lee
    con JavaScript y lo envía en el formulario junto a la clave nueva.
    """

    error = None

    if request.method == "POST":

        token = request.form.get("token", "")
        clave = request.form.get("clave", "")
        confirmacion = request.form.get("confirmacion", "")

        if not token:
            error = "El enlace no es válido o ya expiró. Pide uno nuevo."

        elif len(clave) < LARGO_MINIMO_CLAVE:
            error = f"La clave debe tener al menos {LARGO_MINIMO_CLAVE} caracteres."

        elif clave != confirmacion:
            error = "Las claves no coinciden."

        else:
            _, error = llamar_supabase("PUT", "user", {"password": clave}, token=token)

            if not error:
                session.clear()
                flash("Tu clave fue actualizada. Ya puedes iniciar sesión.")
                return redirect(url_for("login"))

            if "different from the old" in error:
                error = "La clave nueva debe ser distinta a la anterior."

            elif "expired" in error.lower() or "invalid" in error.lower():
                error = "El enlace no es válido o ya expiró. Pide uno nuevo."

    return render_template(
        "nueva_clave.html", error=error, largo_minimo=LARGO_MINIMO_CLAVE
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# DASHBOARD
# =========================

MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


@lru_cache(maxsize=64)
def indicadores_dashboard(D, desde=None, hasta=None):
    """Indicadores de una empresa (D) para el período (fechas o None = sin límite).

    Cada combinación de empresa y período se calcula una vez y se guarda.
    """

    pedidos = fechas.filtrar_por_fecha(D.pedidos, "fecha_pedido_id", desde, hasta)
    entregas = fechas.filtrar_por_fecha(D.entregas, "fecha_salida_id", desde, hasta)
    combustible = fechas.filtrar_por_fecha(D.combustible, "fecha_id", desde, hasta)
    mantenciones = fechas.filtrar_por_fecha(D.mantenciones, "fecha_mantencion_id", desde, hasta)
    incidentes = fechas.filtrar_por_fecha(D.incidentes, "fecha_incidente_id", desde, hasta)

    estados_pedidos = pedidos["estado_pedido"].value_counts().to_dict()
    estados_vehiculos = D.vehiculos["estado"].value_counts().to_dict()

    # Entregas realizadas a tiempo
    a_tiempo = (
        entregas["entrega_a_tiempo"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "si", "sí", "yes", "a tiempo"])
    )

    total_entregas = len(entregas)
    entregas_a_tiempo = int(a_tiempo.sum())

    porcentaje_a_tiempo = (
        round(entregas_a_tiempo / total_entregas * 100, 1)
        if total_entregas > 0 else 0
    )

    # Pedidos por mes (fecha_pedido_id = AAAAMMDD)
    por_mes = (pedidos["fecha_pedido_id"] // 100).value_counts().sort_index()

    pedidos_mes_labels = [
        f"{MESES_CORTOS[int(mes) % 100 - 1]} {int(mes) // 100}"
        for mes in por_mes.index
    ]

    # Costos operacionales
    gasto_combustible = float(combustible["costo_total"].sum())
    costo_mantenciones = float(mantenciones["costo"].sum())
    costo_incidentes = float(incidentes["costo_estimado"].sum())

    return dict(
        total_pedidos=len(pedidos),
        total_vehiculos=len(D.vehiculos),
        total_conductores=len(D.conductores),
        total_rutas=len(D.rutas),
        estados_pedidos=estados_pedidos,
        estados_vehiculos=estados_vehiculos,
        estados_pedidos_labels=list(estados_pedidos.keys()),
        estados_pedidos_valores=list(estados_pedidos.values()),
        estados_vehiculos_labels=list(estados_vehiculos.keys()),
        estados_vehiculos_valores=list(estados_vehiculos.values()),
        vehiculos_disponibles=int((D.vehiculos["estado"] == "Disponible").sum()),
        conductores_activos=int((D.conductores["estado"] == "Activo").sum()),
        total_entregas=total_entregas,
        entregas_a_tiempo=entregas_a_tiempo,
        porcentaje_a_tiempo=porcentaje_a_tiempo,
        gasto_combustible=gasto_combustible,
        costo_mantenciones=costo_mantenciones,
        costo_incidentes=costo_incidentes,
        costo_operacional=gasto_combustible + costo_mantenciones + costo_incidentes,
        pedidos_mes_labels=pedidos_mes_labels,
        pedidos_mes_valores=[int(valor) for valor in por_mes.values],
        promedio_pedidos_mes=round(float(por_mes.mean())) if len(por_mes) else 0,
    )


@app.route("/")
def inicio():

    D = datos_actuales()
    _, contexto_fechas, args_fechas = filtro_de_fechas(D.pedidos, "fecha_pedido_id")
    desde, hasta = fechas.leer_rango(request.args)

    return render_template(
        "dashboard.html",
        fechas=contexto_fechas,
        args_fechas=args_fechas,
        sin_datos=D.vacia,
        **indicadores_dashboard(D, desde, hasta),
    )


# =========================
# PEDIDOS
# =========================

@app.route("/pedidos")
def pedidos():

    D = datos_actuales()

    pedidos_periodo, contexto_fechas, _ = filtro_de_fechas(D.pedidos, "fecha_pedido_id")

    pedidos_filtrados, estado_filtro = filtrar_por_estado(
        pedidos_periodo,
        *FILTROS_ESTADO["pedidos"]
    )

    datos_pedidos, pagina, total_paginas = paginar(pedidos_filtrados)

    # 20250108 -> 08/01/2025
    datos_pedidos["fecha_pedido_id"] = (
        datos_pedidos["fecha_pedido_id"]
        .astype(str)
        .apply(lambda fecha: f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}")
    )

    return render_template(
        "pedidos.html",
        pedidos=datos_pedidos.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(pedidos_filtrados),
        estados_pedidos=pedidos_periodo["estado_pedido"].value_counts().to_dict(),
        estado_filtro=estado_filtro,
        total_pedidos=len(pedidos_periodo),
        fechas=contexto_fechas,
        filtros_url=fechas.args_url(*fechas.leer_rango(request.args), estado=estado_filtro),
    )


# =========================
# VEHÍCULOS
# =========================

@app.route("/vehiculos")
def vehiculos():

    D = datos_actuales()

    vehiculos_filtrados, estado_filtro = filtrar_por_estado(
        D.vehiculos,
        *FILTROS_ESTADO["vehiculos"]
    )

    datos_vehiculos, pagina, total_paginas = paginar(vehiculos_filtrados)

    return render_template(
        "vehiculos.html",
        filtros_url=fechas.args_url(None, None, estado=estado_filtro),
        vehiculos=datos_vehiculos.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(vehiculos_filtrados),
        estados_vehiculos=D.vehiculos["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro,
        total_vehiculos=len(D.vehiculos)
    )


# =========================
# CONDUCTORES
# =========================

@app.route("/conductores")
def conductores():

    D = datos_actuales()

    conductores_filtrados, estado_filtro = filtrar_por_estado(
        D.conductores,
        *FILTROS_ESTADO["conductores"]
    )

    datos_conductores, pagina, total_paginas = paginar(conductores_filtrados)

    return render_template(
        "conductores.html",
        filtros_url=fechas.args_url(None, None, estado=estado_filtro),
        conductores=datos_conductores.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(conductores_filtrados),
        total_conductores=len(D.conductores),
        estados_conductores=D.conductores["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro
    )


# =========================
# RUTAS
# =========================

@app.route("/rutas")
def rutas():

    D = datos_actuales()

    rutas_filtradas, estado_filtro = filtrar_por_estado(
        D.rutas,
        *FILTROS_ESTADO["rutas"]
    )

    datos_rutas, pagina, total_paginas = paginar(rutas_filtradas)

    return render_template(
        "rutas.html",
        filtros_url=fechas.args_url(None, None, estado=estado_filtro),
        rutas=datos_rutas.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(rutas_filtradas),
        total_rutas=len(D.rutas),
        estados_rutas=D.rutas["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro
    )


# =========================
# MANTENCIONES
# =========================

@app.route("/mantenciones")
def mantenciones():

    D = datos_actuales()

    mantenciones_periodo, contexto_fechas, filtros_url = filtro_de_fechas(
        D.mantenciones, "fecha_mantencion_id"
    )

    datos_mantenciones, pagina, total_paginas = paginar(mantenciones_periodo)

    datos_mantenciones["fecha_mantencion_id"] = fecha_guiones(
        datos_mantenciones["fecha_mantencion_id"]
    )

    datos_mantenciones["patente"] = (
        datos_mantenciones["vehiculo_id"].map(D.mapa_patentes).fillna("")
    )

    return render_template(
        "mantenciones.html",
        mantenciones=datos_mantenciones.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(mantenciones_periodo),
        vehiculos_mantencion=mantenciones_periodo["vehiculo_id"].nunique(),
        costo_total=mantenciones_periodo["costo"].sum(),
        fechas=contexto_fechas,
        filtros_url=filtros_url,
    )


# =========================
# COMBUSTIBLE
# =========================

@app.route("/combustible")
def combustible():

    D = datos_actuales()

    combustible_periodo, contexto_fechas, filtros_url = filtro_de_fechas(
        D.combustible, "fecha_id"
    )

    datos_combustible, pagina, total_paginas = paginar(combustible_periodo)

    datos_combustible["fecha_id"] = fecha_guiones(
        datos_combustible["fecha_id"]
    )

    datos_combustible["patente"] = (
        datos_combustible["vehiculo_id"].map(D.mapa_patentes).fillna("")
    )

    return render_template(
        "combustible.html",
        combustible=datos_combustible.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(combustible_periodo),
        vehiculos_registrados=combustible_periodo["vehiculo_id"].nunique(),
        gasto_total=combustible_periodo["costo_total"].sum(),
        fechas=contexto_fechas,
        filtros_url=filtros_url,
    )


# =========================
# INCIDENTES
# =========================

@app.route("/incidentes")
def incidentes():

    D = datos_actuales()

    incidentes_periodo, contexto_fechas, _ = filtro_de_fechas(D.incidentes, "fecha_incidente_id")

    incidentes_filtrados, estado_filtro = filtrar_por_estado(
        incidentes_periodo,
        *FILTROS_ESTADO["incidentes"]
    )

    datos_incidentes, pagina, total_paginas = paginar(incidentes_filtrados)

    datos_incidentes["fecha_incidente_id"] = fecha_guiones(
        datos_incidentes["fecha_incidente_id"]
    )

    datos_incidentes["patente"] = (
        datos_incidentes["vehiculo_id"].map(D.mapa_patentes).fillna("")
    )

    datos_incidentes["nombre_conductor"] = (
        datos_incidentes["conductor_id"]
        .map(D.conductores.set_index("conductor_id")["nombre_conductor"])
        .fillna(datos_incidentes["conductor_id"].astype(str))
    )

    return render_template(
        "incidentes.html",
        incidentes=datos_incidentes.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(incidentes_filtrados),
        incidentes_abiertos=int(incidentes_periodo["estado_incidente"].eq("Abierto").sum()),
        incidentes_resueltos=int(incidentes_periodo["estado_incidente"].eq("Resuelto").sum()),
        total_incidentes=len(incidentes_periodo),
        estado_filtro=estado_filtro,
        fechas=contexto_fechas,
        filtros_url=fechas.args_url(*fechas.leer_rango(request.args), estado=estado_filtro),
    )


@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template("404.html"), 404


# =========================
# DETALLE DE CONDUCTOR Y VEHÍCULO
# =========================

@app.route("/conductores/<int:conductor_id>")
def pagina_conductor(conductor_id):

    D = datos_actuales()

    datos = detalle.detalle_conductor(
        conductor_id, D.conductores, D.entregas, D.incidentes, D.rutas, D.vehiculos
    )

    if datos is None:
        abort(404)

    return render_template("detalle_conductor.html", **datos)


@app.route("/vehiculos/<int:vehiculo_id>")
def pagina_vehiculo(vehiculo_id):

    D = datos_actuales()

    datos = detalle.detalle_vehiculo(
        vehiculo_id, D.vehiculos, D.entregas, D.mantenciones,
        D.combustible, D.incidentes, D.conductores
    )

    if datos is None:
        abort(404)

    return render_template("detalle_vehiculo.html", **datos)


# =========================
# EXPORTAR A EXCEL
# =========================

def datos_para_exportar(seccion):
    """Tabla completa de la sección, con nombres legibles agregados."""

    D = datos_actuales()

    if seccion == "pedidos":
        df = D.pedidos.copy()
        df["nombre_cliente"] = df["cliente_id"].map(
            D.clientes.set_index("cliente_id")["nombre_cliente"]
        )
        return df

    if seccion == "incidentes":
        df = D.incidentes.copy()
        df["patente"] = df["vehiculo_id"].map(D.mapa_patentes)
        df["nombre_conductor"] = df["conductor_id"].map(
            D.conductores.set_index("conductor_id")["nombre_conductor"]
        )
        return df

    if seccion in ("mantenciones", "combustible"):
        df = (D.mantenciones if seccion == "mantenciones" else D.combustible).copy()
        df["patente"] = df["vehiculo_id"].map(D.mapa_patentes)
        return df

    return {
        "vehiculos": D.vehiculos,
        "conductores": D.conductores,
        "rutas": D.rutas,
    }[seccion].copy()


def hora_chile():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Santiago"))
    except Exception:  # sin base de zonas horarias en el equipo
        return datetime.now()


@app.route("/exportar/<seccion>")
def exportar(seccion):

    secciones = ("pedidos", "vehiculos", "conductores", "rutas",
                 "mantenciones", "combustible", "incidentes")

    if seccion not in secciones:
        abort(404)

    df = datos_para_exportar(seccion)
    filtro = None

    if seccion in COLUMNAS_FECHA:
        desde, hasta = fechas.leer_rango(request.args)
        df = fechas.filtrar_por_fecha(df, COLUMNAS_FECHA[seccion], desde, hasta)
    else:
        desde = hasta = None

    if seccion in FILTROS_ESTADO:
        df, filtro = filtrar_por_estado(df, *FILTROS_ESTADO[seccion])

    fecha = hora_chile()
    periodo = fechas.describir(desde, hasta) if (desde or hasta) else None

    return send_file(
        crear_excel(df, seccion, filtro, fecha, periodo),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=nombre_archivo(seccion, filtro, fecha, desde, hasta),
    )


# =========================
# ASISTENTE CON IA
# =========================

_asistentes = {}  # id de los datos de la empresa -> Asistente


def asistente_actual():
    """Asistente que responde con los datos de la empresa de la sesión."""

    D = datos_actuales()
    clave = id(D)

    if clave not in _asistentes:
        if len(_asistentes) > 20:  # no acumular asistentes de datos antiguos
            _asistentes.clear()
        _asistentes[clave] = Asistente(
            construir_tablas(
                D.pedidos, D.entregas, D.vehiculos, D.conductores, D.rutas,
                D.clientes, D.mantenciones, D.combustible, D.incidentes,
            ),
            resumen=lambda: indicadores_dashboard(D),
        )

    return _asistentes[clave]


def ia_disponible():
    return configuracion_ia()[0] is not None

# Límite de preguntas por sesión (cuida el saldo o la cuota gratis de la IA)
PREGUNTAS_POR_HORA = 40
LARGO_MAXIMO_PREGUNTA = 500


@app.route("/asistente")
def pagina_asistente():
    return render_template("asistente.html", disponible=ia_disponible())


@app.route("/asistente/preguntar", methods=["POST"])
def preguntar_asistente():

    if not ia_disponible():
        return jsonify(error="Falta configurar GEMINI_API_KEY (o OPENAI_API_KEY)."), 503

    datos = request.get_json(silent=True) or {}
    pregunta = str(datos.get("pregunta", "")).strip()
    historial = datos.get("historial") or []

    if not pregunta:
        return jsonify(error="Escribe una pregunta."), 400

    if len(pregunta) > LARGO_MAXIMO_PREGUNTA:
        return jsonify(error=f"La pregunta puede tener hasta {LARGO_MAXIMO_PREGUNTA} caracteres."), 400

    # Contar preguntas de la última hora
    ahora = time.time()
    usos = [t for t in session.get("usos_ia", []) if ahora - t < 3600]

    if len(usos) >= PREGUNTAS_POR_HORA:
        return jsonify(error="Llegaste al límite de preguntas por hora. Intenta más tarde."), 429

    session["usos_ia"] = usos + [ahora]

    # Solo los últimos mensajes, para que la consulta sea corta y barata
    historial = [m for m in historial if isinstance(m, dict)][-8:]

    try:
        respuesta = asistente_actual().responder(pregunta, historial)

    except Exception as error:
        # Queda en los registros (Logs) de Vercel con el detalle completo
        app.logger.exception("Error del asistente: %s", getattr(error, "message", error))
        return jsonify(error=mensaje_error_ia(error)), 502

    return jsonify(respuesta=respuesta)


def mensaje_error_ia(error):
    """Traduce los errores del proveedor de IA a un mensaje entendible."""

    nombre = type(error).__name__

    if nombre == "AuthenticationError":
        return "La clave de la IA no es válida. Revisa GEMINI_API_KEY (o OPENAI_API_KEY)."

    if nombre == "RateLimitError":
        return ("Se alcanzó el límite de uso de la IA. Si usas el plan gratis, "
                "espera un minuto e intenta de nuevo.")

    if nombre == "NotFoundError":
        return "El modelo de IA configurado no está disponible. Revisa GEMINI_MODEL u OPENAI_MODEL."

    if nombre == "PermissionDeniedError":
        return "La clave de la IA no tiene permiso para esta consulta."

    if nombre == "InternalServerError":
        return ("El servicio de IA está saturado en este momento (es común en el plan gratis). "
                "Intenta de nuevo en unos segundos.")

    if nombre in ("APIConnectionError", "APITimeoutError"):
        return "No se pudo conectar con el servicio de IA. Intenta de nuevo."

    # Se muestra el tipo y código del error (sin datos privados) para diagnosticar
    codigo = getattr(error, "status_code", None)
    detalle = f"{nombre} {codigo}" if codigo else nombre
    return f"Ocurrió un error al consultar la IA ({detalle}). Intenta de nuevo."


# =========================
# EJECUTAR APLICACIÓN
# =========================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1"
    )
