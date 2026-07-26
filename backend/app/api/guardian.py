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


@router.get("/guardian/probar")
async def probar(request: Request) -> dict:
    """Prueba el Guardian de punta a punta con una pantalla peligrosa
    inventada, y cuenta TODO lo que ha pasado.

    Existe porque no se puede estar dependiendo de que alguien instale
    la app en un movil y cuente por escrito lo que ve: asi se tarda una
    hora en descubrir algo que aqui se ve en diez segundos.
    """
    servicio = getattr(request.app.state, "guardian", None)
    if servicio is None:
        return {"error": "el servicio no ha arrancado"}

    pantalla = Pantalla(
        dominio="tienda-de-prueba.es",
        titulo="Finalizar compra",
        encabezados=["Resumen de su pedido"],
        botones=["Seguir comprando", "Comprar ahora"],
        campos=[{
            "etiqueta": "Contratar seguro de envío por 4,99 € al mes",
            "tipo": "checkbox", "marcada": True, "vacia": True,
        }],
        textos=["Al continuar acepta la renovación automática de su suscripción mensual."],
        importes=["49,90 €"],
    )

    # Sin memoria: si no, la segunda prueba contestaria de carrerilla
    servicio._memoria.clear()
    servicio.diario.clear()

    aviso = await servicio.analizar(pantalla)
    return {
        "lo_que_ha_pasado": servicio.diario,
        "resultado": aviso.model_dump(),
        "veredicto": (
            "LA IA FUNCIONA" if aviso.hay_aviso
            else "LA IA NO ESTA CONTESTANDO (mira lo_que_ha_pasado)"
        ),
    }


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
        "lo_ultimo_que_ha_pasado": s.diario[-8:],
    }
