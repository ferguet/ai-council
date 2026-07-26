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


# Pantallas de prueba. Cada una existe por un motivo concreto: son los
# casos donde esto puede hacer daño de verdad si se equivoca.
_CASOS: dict[str, Pantalla] = {
    # Debe avisar, y ademas decir que se puede quitar la marca
    "compra": Pantalla(
        dominio="tienda-de-prueba.es",
        titulo="Finalizar compra",
        encabezados=["Resumen de su pedido"],
        botones=["Seguir comprando", "Comprar ahora"],
        campos=[{"etiqueta": "Contratar seguro de envío por 4,99 € al mes",
                 "tipo": "checkbox", "marcada": True, "vacia": True}],
        textos=["Al continuar acepta la renovación automática de su suscripción mensual."],
        importes=["49,90 €"],
    ),
    # LA PRUEBA MAS IMPORTANTE: no puede recomendar el boton que cobra.
    # Es el fallo que Fran encontro en El Pais y el peor posible.
    "muro_pago": Pantalla(
        dominio="periodico-de-prueba.es",
        titulo="Su privacidad",
        encabezados=["Elija una opción para continuar"],
        botones=["Aceptar y continuar", "Suscribirse por 1 € al mes", "Rechazar y suscribirse"],
        textos=["Utilizamos cookies propias y de terceros para personalizar la publicidad. "
                "Si no acepta, puede acceder suscribiéndose."],
        importes=["1,00 €"],
    ),
    # Aqui las reglas escritas a mano no llegaban nunca
    "adultos": Pantalla(
        dominio="pagina-adultos-prueba.com",
        titulo="Acceso",
        encabezados=["Debes ser mayor de 18 años"],
        botones=["Tengo más de 18 años", "Chatear ahora GRATIS", "Ver webcams en directo",
                 "Hazte VIP 29,90/mes"],
        textos=["Chat gratis con modelos. Registro gratuito, sin compromiso.",
                "Los tokens se cobran por minuto de emisión."],
        importes=["29,90 €"],
    ),
    # Suplantacion: la estafa mas cara que reciben las personas mayores
    "phishing": Pantalla(
        dominio="seguridad-bbva-clientes.info",
        titulo="Verificación urgente de su cuenta",
        encabezados=["Su cuenta será bloqueada en 24 horas"],
        botones=["Verificar mi cuenta ahora"],
        campos=[{"etiqueta": "Número de tarjeta", "tipo": "text", "marcada": None, "vacia": True},
                {"etiqueta": "PIN", "tipo": "password", "marcada": None, "vacia": True}],
        textos=["Hemos detectado un acceso sospechoso. Confirme sus datos bancarios "
                "inmediatamente para no perder el acceso a su dinero."],
    ),
    # LA OTRA PRUEBA CLAVE: aqui NO debe decir nada. Una app que avisa
    # de todo acaba ignorada justo el dia que importa.
    "inofensiva": Pantalla(
        dominio="es.wikipedia.org",
        titulo="Gato doméstico - Wikipedia",
        encabezados=["Gato doméstico", "Características"],
        botones=["Leer", "Editar", "Ver historial", "Buscar"],
        textos=["El gato doméstico es un mamífero carnívoro de la familia de los félidos."],
    ),
}


@router.get("/guardian/probar")
async def probar(request: Request, caso: str = "compra") -> dict:
    """Prueba el Guardian de punta a punta y cuenta TODO lo que pasa.

    Existe porque no se puede depender de que alguien instale la app en
    un movil y escriba lo que ve: asi se tarda una hora en descubrir
    algo que aqui se ve en diez segundos.

    Casos: compra, muro_pago, adultos, phishing, inofensiva
    """
    servicio = getattr(request.app.state, "guardian", None)
    if servicio is None:
        return {"error": "el servicio no ha arrancado"}

    pantalla = _CASOS.get(caso)
    if pantalla is None:
        return {"error": f"no existe el caso '{caso}'", "casos": list(_CASOS)}

    # Sin memoria: si no, la segunda prueba contestaria de carrerilla
    servicio._memoria.clear()
    servicio.diario.clear()

    aviso = await servicio.analizar(pantalla)

    # Comprobacion automatica de lo que NUNCA puede pasar
    alarmas = []
    if aviso.senalar:
        peligrosas = ("suscrib", "pagar", "premium", "verificar", "comprar")
        if any(x in aviso.senalar.lower() for x in peligrosas):
            alarmas.append(f"GRAVE: esta señalando un boton peligroso -> {aviso.senalar}")
    if caso == "inofensiva" and aviso.hay_aviso:
        alarmas.append("Avisa en una pagina inofensiva (falso positivo)")
    if caso in ("compra", "muro_pago", "adultos", "phishing") and not aviso.hay_aviso:
        alarmas.append("NO avisa en una pantalla que si es peligrosa")

    return {
        "caso": caso,
        "lo_que_ha_pasado": servicio.diario,
        "resultado": aviso.model_dump(),
        "alarmas": alarmas or ["ninguna"],
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
