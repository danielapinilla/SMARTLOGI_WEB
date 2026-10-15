import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask, flash, redirect, render_template, request, session, url_for
)
from werkzeug.middleware.proxy_fix import ProxyFix

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

# Correos con permiso de administrador, separados por coma.
# Si se deja vacío, cualquier usuario de Supabase puede entrar.
ADMIN_EMAILS = {
    correo.strip().lower()
    for correo in os.environ.get("ADMIN_EMAILS", "").split(",")
    if correo.strip()
}

REGISTROS_POR_PAGINA = 50


@app.template_filter("miles")
def formato_miles(valor):
    return f"{valor:,}".replace(",", ".")


# =========================
# CARGAR DATOS
# =========================

CARPETA_DATOS = Path(__file__).resolve().parent / "data"


def leer_csv(nombre):
    return pd.read_csv(CARPETA_DATOS / nombre)


pedidos_df = leer_csv("fact_pedidos_10000.csv")
vehiculos_df = leer_csv("dim_vehiculos_30.csv")
conductores_df = leer_csv("dim_conductores_50.csv")
rutas_df = leer_csv("dim_rutas_100.csv")
mantenciones_df = leer_csv("fact_mantenciones_1000.csv")
combustible_df = leer_csv("fact_combustible_3000.csv")
incidentes_df = leer_csv("fact_incidentes_500.csv")
entregas_df = leer_csv("fact_entregas.csv")

mapa_patentes = (
    vehiculos_df
    .set_index("vehiculo_id")["patente"]
    .to_dict()
)


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
PAGINAS_PUBLICAS = {"login", "recuperar_clave", "nueva_clave", "static"}


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

        elif ADMIN_EMAILS and correo not in ADMIN_EMAILS:
            error = "Este correo no tiene acceso de administrador."

        else:
            respuesta, error = llamar_supabase(
                "POST",
                "token?grant_type=password",
                {"email": correo, "password": clave},
            )

            if respuesta:
                usuario = respuesta.get("user") or {}
                session.clear()
                session.permanent = True
                session["usuario"] = usuario.get("email", correo)
                return redirect(destino_seguro(request.args.get("next")))

            # No mostrar el detalle técnico de Supabase al usuario
            if not error.startswith("No se pudo conectar"):
                error = "Correo o clave incorrectos."

    return render_template("login.html", error=error, correo=correo)


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
            # Solo se envía el correo a administradores, pero el mensaje
            # es el mismo para todos: así nadie puede averiguar qué correos existen.
            if not ADMIN_EMAILS or correo in ADMIN_EMAILS:
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

@lru_cache(maxsize=1)
def indicadores_dashboard():
    """Los CSV no cambian mientras la app corre, así que se calcula una vez."""

    estados_pedidos = pedidos_df["estado_pedido"].value_counts().to_dict()
    estados_vehiculos = vehiculos_df["estado"].value_counts().to_dict()

    # Entregas realizadas a tiempo
    a_tiempo = (
        entregas_df["entrega_a_tiempo"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "si", "sí", "yes", "a tiempo"])
    )

    total_entregas = len(entregas_df)
    entregas_a_tiempo = int(a_tiempo.sum())

    porcentaje_a_tiempo = (
        round(entregas_a_tiempo / total_entregas * 100, 1)
        if total_entregas > 0 else 0
    )

    # Costos operacionales
    gasto_combustible = float(combustible_df["costo_total"].sum())
    costo_mantenciones = float(mantenciones_df["costo"].sum())
    costo_incidentes = float(incidentes_df["costo_estimado"].sum())

    return dict(
        total_pedidos=len(pedidos_df),
        total_vehiculos=len(vehiculos_df),
        total_conductores=len(conductores_df),
        total_rutas=len(rutas_df),
        estados_pedidos=estados_pedidos,
        estados_vehiculos=estados_vehiculos,
        estados_pedidos_labels=list(estados_pedidos.keys()),
        estados_pedidos_valores=list(estados_pedidos.values()),
        estados_vehiculos_labels=list(estados_vehiculos.keys()),
        estados_vehiculos_valores=list(estados_vehiculos.values()),
        vehiculos_disponibles=int((vehiculos_df["estado"] == "Disponible").sum()),
        conductores_activos=int((conductores_df["estado"] == "Activo").sum()),
        total_entregas=total_entregas,
        entregas_a_tiempo=entregas_a_tiempo,
        porcentaje_a_tiempo=porcentaje_a_tiempo,
        gasto_combustible=gasto_combustible,
        costo_mantenciones=costo_mantenciones,
        costo_incidentes=costo_incidentes,
        costo_operacional=gasto_combustible + costo_mantenciones + costo_incidentes,
    )


@app.route("/")
def inicio():
    return render_template("dashboard.html", **indicadores_dashboard())


# =========================
# PEDIDOS
# =========================

@app.route("/pedidos")
def pedidos():

    pedidos_filtrados, estado_filtro = filtrar_por_estado(
        pedidos_df,
        "estado_pedido",
        ["Todos", "Entregado", "En ruta", "En preparación", "Pendiente", "Cancelado"]
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
        estados_pedidos=pedidos_df["estado_pedido"].value_counts().to_dict(),
        estado_filtro=estado_filtro,
        total_pedidos=len(pedidos_df)
    )


# =========================
# VEHÍCULOS
# =========================

@app.route("/vehiculos")
def vehiculos():

    vehiculos_filtrados, estado_filtro = filtrar_por_estado(
        vehiculos_df,
        "estado",
        ["Todos", "Disponible", "En ruta", "Mantención"]
    )

    datos_vehiculos, pagina, total_paginas = paginar(vehiculos_filtrados)

    return render_template(
        "vehiculos.html",
        vehiculos=datos_vehiculos.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(vehiculos_filtrados),
        estados_vehiculos=vehiculos_df["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro,
        total_vehiculos=len(vehiculos_df)
    )


# =========================
# CONDUCTORES
# =========================

@app.route("/conductores")
def conductores():

    conductores_filtrados, estado_filtro = filtrar_por_estado(
        conductores_df,
        "estado",
        ["Todos", "Activo", "Inactivo", "Licencia médica", "Vacaciones"]
    )

    datos_conductores, pagina, total_paginas = paginar(conductores_filtrados)

    return render_template(
        "conductores.html",
        conductores=datos_conductores.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(conductores_filtrados),
        total_conductores=len(conductores_df),
        estados_conductores=conductores_df["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro
    )


# =========================
# RUTAS
# =========================

@app.route("/rutas")
def rutas():

    rutas_filtradas, estado_filtro = filtrar_por_estado(
        rutas_df,
        "estado",
        ["Todos", "Activa", "Restringida", "Suspendida"]
    )

    datos_rutas, pagina, total_paginas = paginar(rutas_filtradas)

    return render_template(
        "rutas.html",
        rutas=datos_rutas.to_dict(orient="records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(rutas_filtradas),
        total_rutas=len(rutas_df),
        estados_rutas=rutas_df["estado"].value_counts().to_dict(),
        estado_filtro=estado_filtro
    )


# =========================
# MANTENCIONES
# =========================

@app.route("/mantenciones")
def mantenciones():

    datos_mantenciones, pagina, total_paginas = paginar(mantenciones_df)

    datos_mantenciones["fecha_mantencion_id"] = fecha_guiones(
        datos_mantenciones["fecha_mantencion_id"]
    )

    datos_mantenciones["patente"] = (
        datos_mantenciones["vehiculo_id"].map(mapa_patentes).fillna("")
    )

    return render_template(
        "mantenciones.html",
        mantenciones=datos_mantenciones.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(mantenciones_df),
        vehiculos_mantencion=mantenciones_df["vehiculo_id"].nunique(),
        costo_total=mantenciones_df["costo"].sum()
    )


# =========================
# COMBUSTIBLE
# =========================

@app.route("/combustible")
def combustible():

    datos_combustible, pagina, total_paginas = paginar(combustible_df)

    datos_combustible["fecha_id"] = fecha_guiones(
        datos_combustible["fecha_id"]
    )

    datos_combustible["patente"] = (
        datos_combustible["vehiculo_id"].map(mapa_patentes).fillna("")
    )

    return render_template(
        "combustible.html",
        combustible=datos_combustible.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(combustible_df),
        vehiculos_registrados=combustible_df["vehiculo_id"].nunique(),
        gasto_total=combustible_df["costo_total"].sum()
    )


# =========================
# INCIDENTES
# =========================

# Convertir la columna "resuelto" a un estado visible
incidentes_df["estado_incidente"] = (
    incidentes_df["resuelto"]
    .astype(str)
    .str.strip()
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


@app.route("/incidentes")
def incidentes():

    incidentes_filtrados, estado_filtro = filtrar_por_estado(
        incidentes_df,
        "estado_incidente",
        ["Todos", "Abierto", "Resuelto"]
    )

    datos_incidentes, pagina, total_paginas = paginar(incidentes_filtrados)

    datos_incidentes["fecha_incidente_id"] = fecha_guiones(
        datos_incidentes["fecha_incidente_id"]
    )

    datos_incidentes["patente"] = (
        datos_incidentes["vehiculo_id"].map(mapa_patentes).fillna("")
    )

    return render_template(
        "incidentes.html",
        incidentes=datos_incidentes.to_dict("records"),
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=len(incidentes_filtrados),
        incidentes_abiertos=int(incidentes_df["estado_incidente"].eq("Abierto").sum()),
        incidentes_resueltos=int(incidentes_df["estado_incidente"].eq("Resuelto").sum()),
        estado_filtro=estado_filtro
    )


# =========================
# EJECUTAR APLICACIÓN
# =========================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1"
    )
