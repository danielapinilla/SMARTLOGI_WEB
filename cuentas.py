"""Empresas y usuarios en Supabase (con la clave secreta del servidor).

La clave secreta (SUPABASE_SERVICE_KEY) solo existe en el servidor:
nunca se envía al navegador.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ErrorCuenta(Exception):
    """Error con un mensaje que se puede mostrar a la persona."""


def configurado():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


def _llamar(metodo, ruta, datos=None, cabeceras_extra=None):
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/").removesuffix("/rest/v1")
    clave = os.environ.get("SUPABASE_SERVICE_KEY", "")

    cabeceras = {
        "apikey": clave,
        "Authorization": f"Bearer {clave}",
        "Content-Type": "application/json",
    }
    cabeceras.update(cabeceras_extra or {})

    peticion = urllib.request.Request(
        f"{url}{ruta}",
        data=json.dumps(datos).encode() if datos is not None else None,
        headers=cabeceras,
        method=metodo,
    )

    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            cuerpo = respuesta.read()
            return json.loads(cuerpo) if cuerpo else None

    except urllib.error.HTTPError as error:
        try:
            detalle = json.load(error)
        except ValueError:
            detalle = {}
        mensaje = detalle.get("msg") or detalle.get("message") or detalle.get("error_description") or ""
        raise ErrorCuenta(mensaje or f"Error {error.code}") from error

    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorCuenta("No se pudo conectar con el servidor. Intenta de nuevo.") from error


def registrar_empresa(nombre_empresa, nombre_persona, correo, clave):
    """Crea el usuario, la empresa y los une. Devuelve (user_id, empresa_id).

    Si algo falla a mitad de camino, deshace lo que alcanzó a crear.
    """

    try:
        usuario = _llamar("POST", "/auth/v1/admin/users", {
            "email": correo,
            "password": clave,
            "email_confirm": True,  # sin correo de confirmación
            "user_metadata": {"nombre": nombre_persona},
        })
    except ErrorCuenta as error:
        texto = str(error).lower()
        if "already" in texto or "registered" in texto or "exists" in texto:
            raise ErrorCuenta("Ya existe una cuenta con ese correo. Inicia sesión.") from error
        if "password" in texto:
            raise ErrorCuenta("La clave no cumple los requisitos. Usa al menos 8 caracteres.") from error
        raise

    user_id = usuario["id"]

    try:
        empresa = _llamar(
            "POST", "/rest/v1/empresas", {"nombre": nombre_empresa},
            {"Prefer": "return=representation"},
        )[0]

        _llamar("POST", "/rest/v1/miembros", {
            "user_id": user_id,
            "empresa_id": empresa["id"],
            "nombre": nombre_persona,
            "rol": "admin",
        })

    except ErrorCuenta:
        # Deshacer: borrar el usuario (y la empresa, si alcanzó a crearse)
        try:
            _llamar("DELETE", f"/auth/v1/admin/users/{user_id}")
        except ErrorCuenta:
            pass
        raise ErrorCuenta("No se pudo crear la empresa. Intenta de nuevo.")

    return user_id, empresa["id"]


def empresa_de_usuario(user_id):
    """Devuelve {"empresa_id", "empresa", "nombre"} o None si no pertenece a ninguna."""

    consulta = urllib.parse.urlencode({
        "user_id": f"eq.{user_id}",
        "select": "empresa_id,nombre,empresas(nombre)",
    })
    filas = _llamar("GET", f"/rest/v1/miembros?{consulta}")

    if not filas:
        return None

    fila = filas[0]
    return {
        "empresa_id": fila["empresa_id"],
        "empresa": (fila.get("empresas") or {}).get("nombre", "Mi empresa"),
        "nombre": fila.get("nombre"),
    }
