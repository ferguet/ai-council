"""
Puerta de entrada de la app (clave compartida) + identidad de visitante.

No es un sistema de cuentas con usuario/contrasena: es UNA clave que Fran
reparte a mano a quien quiere que entre. Quien la acierta una vez recibe un
"visitor_id" firmado que el navegador guarda (localStorage) y manda en cada
peticion; ese id es tambien lo que separa las conversaciones de cada
persona (cada visitante ve solo las suyas, no las de los demas).

El token es "visitor_id.firma" donde firma = HMAC-SHA256(ACCESS_CODE,
visitor_id). No hace falta guardar una lista de tokens validos en ningun
sitio: cualquiera con la clave correcta puede volver a verificar la firma.
Si Fran quiere cortarle el paso a todo el mundo de golpe (p.ej. el enlace
se filtro a quien no debia), le basta con cambiar ACCESS_CODE en Render:
todos los tokens ya repartidos dejan de validar en el siguiente arranque.

Sin ACCESS_CODE configurada la puerta esta abierta (para poder desarrollar
en local sin tener que montarla).
"""
from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import Header, HTTPException

from app.core.config import get_settings


def _sign(visitor_id: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), visitor_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def new_visitor_id() -> str:
    return uuid.uuid4().hex[:16]


def issue_token(visitor_id: str) -> str:
    """El token que el frontend guarda y manda en cada peticion."""
    settings = get_settings()
    if not settings.access_code:
        return visitor_id
    return f"{visitor_id}.{_sign(visitor_id, settings.access_code)}"


def verify_token(token: str | None) -> str | None:
    """Devuelve el visitor_id si el token es valido, o None si no lo es."""
    settings = get_settings()
    if not token:
        return None
    if not settings.access_code:
        # Puerta abierta: se confia en el id que mande el navegador tal cual
        # (puede venir con o sin firma de una sesion anterior con puerta
        # cerrada; en cualquier caso no hay clave que validar ahora mismo).
        return token.split(".", 1)[0]
    if "." not in token:
        return None
    visitor_id, sig = token.rsplit(".", 1)
    if not visitor_id or not hmac.compare_digest(sig, _sign(visitor_id, settings.access_code)):
        return None
    return visitor_id


def check_code(code: str) -> bool:
    settings = get_settings()
    if not settings.access_code:
        return True
    return hmac.compare_digest((code or "").strip(), settings.access_code.strip())


def gate_enabled() -> bool:
    return bool(get_settings().access_code)


async def require_visitor(
    x_visitor_token: str | None = Header(default=None, alias="X-Visitor-Token"),
) -> str:
    """Dependency para rutas REST: exige un token de visitante valido."""
    visitor_id = verify_token(x_visitor_token)
    if not visitor_id:
        raise HTTPException(status_code=401, detail="Falta la clave de acceso o no es valida")
    return visitor_id


def require_visitor_ws(token: str | None) -> str | None:
    """Misma verificacion que require_visitor pero para WebSocket, donde no
    hay forma comoda de lanzar un HTTPException: el propio route handler
    decide que hacer (normalmente cerrar la conexion) si esto da None."""
    return verify_token(token)
