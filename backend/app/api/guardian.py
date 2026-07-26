"""
API del Guardian: la usa la app de acompañamiento a personas mayores.

No lleva la puerta de acceso (ACCESS_CODE) del resto del proyecto a
proposito: esto no es para invitados de Fran, es un servicio que tiene
que funcionar en el movil de cualquier persona mayor sin que nadie le
haya dado ninguna clave. La proteccion contra abusos va por otro lado:
limite de peticiones por movil y racionamiento de cuota.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Header, HTTPException, Request

from app.guardian.models import Aviso, Pantalla

router = APIRouter(tags=["guardian"])

# Limite por movil: 40 consultas cada 10 minutos. Con la memoria de
# pantallas del servicio, un uso normal se queda muy por debajo. Esto es
# solo para que nadie monte un bucle y se lleve la cuota por delante.
_VENTANA = 600
_TOPE = 40
_visitas: dict[str, deque] = defaultdict(deque)


def _permitido(quien: str) -> bool:
    ahora = time.time()
    cola = _visitas[quien]
    while cola and ahora - cola[0] > _VENTANA:
        cola.popleft()
    if len(cola) >= _TOPE:
        return False
    cola.append(ahora)
    return True


@router.post("/guardian/mirar", response_model=Aviso)
async def mirar(
    pantalla: Pantalla,
    request: Request,
    x_movil: str = Header(default="anonimo"),
) -> Aviso:
    """Mira una pantalla y dice si hay que avisar de algo.

    Nunca recibe datos personales: ver app/guardian/models.py, donde se
    explica por que los modelos estan hechos para que no quepan.
    """
    if not _permitido(x_movil[:64]):
        # No se devuelve error: se devuelve "no hay aviso". La app tiene
        # que seguir funcionando con sus reglas pase lo que pase, sin
        # enseñarle a la persona ningun mensaje raro.
        return Aviso(motivo="demasiadas consultas seguidas")

    servicio = getattr(request.app.state, "guardian", None)
    if servicio is None:
        return Aviso(motivo="servicio no disponible")

    try:
        return await servicio.analizar(pantalla)
    except Exception:
        return Aviso(motivo="fallo al analizar")


@router.get("/guardian/salud")
def salud(request: Request) -> dict:
    """Para saber si esto esta vivo y cuanto se esta ahorrando con la
    memoria de pantallas (cuantas consultas no han llegado a la IA)."""
    s = getattr(request.app.state, "guardian", None)
    if s is None:
        return {"vivo": False}
    total = max(1, s.consultas)
    return {
        "vivo": True,
        "consultas": s.consultas,
        "servidas_de_memoria": s.aciertos_memoria,
        "ahorro": f"{round(s.aciertos_memoria / total * 100)}%",
    }
