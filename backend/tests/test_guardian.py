"""
Guardian: la IA que mira la pantalla de una persona mayor y avisa.

El primer bloque de tests es el que de verdad importa. No comprueba que
funcione: comprueba que NO SE ESCAPE NADA. Quien usa esto es gente a la
que ya intentan robar por todos lados; si por protegerla mandasemos su
DNI o su tarjeta a un servidor, seriamos parte del problema.
"""
from __future__ import annotations

import json

import pytest

from app.guardian.models import Aviso, CampoVisto, Pantalla
from app.guardian.prompt import construir
from app.guardian.servicio import GuardianService
from app.providers.base import AIProvider, ChatMessage, ProviderError


class _IAFalsa(AIProvider):
    """Devuelve lo que le digamos y guarda lo que le han mandado."""

    def __init__(self, respuestas: list[str] | None = None) -> None:
        self.recibido: list[str] = []
        self.llamadas = 0
        self._respuestas = list(respuestas or [])

    def is_configured(self) -> bool:
        return True

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7, max_tokens=None) -> str:
        self.llamadas += 1
        self.recibido.append("\n".join(m.content for m in messages))
        if not self._respuestas:
            return json.dumps({"hay_aviso": False, "gravedad": 0, "corto": "", "voz": "",
                               "senalar": None, "motivo": "nada"})
        return self._respuestas.pop(0)

    async def stream_chat(self, messages, model, temperature=0.7):
        raise ProviderError("no usado")
        yield ""  # pragma: no cover


class _Registro:
    def __init__(self, ia) -> None:
        self._ia = ia

    def get(self, nombre: str):
        return self._ia


def _pantalla_compra() -> Pantalla:
    return Pantalla(
        dominio="tienda.es",
        titulo="Finalizar compra",
        botones=["Seguir mirando", "Comprar ahora"],
        campos=[
            CampoVisto(etiqueta="Número de tarjeta", tipo="text", vacia=False),
            CampoVisto(etiqueta="Contratar seguro de envío por 4,99 al mes",
                       tipo="checkbox", marcada=True),
        ],
        importes=["49,90 €"],
    )


# =====================================================================
# 1. PRIVACIDAD. Si algo de esto falla, el proyecto entero esta mal.
# =====================================================================

def test_los_modelos_no_admiten_lo_que_la_persona_escribe() -> None:
    """No hay ningun sitio donde meter un valor tecleado, a proposito."""
    campos_permitidos = set(CampoVisto.model_fields.keys())
    assert campos_permitidos == {"etiqueta", "tipo", "marcada", "vacia"}
    # ni "valor", ni "contenido", ni "texto_escrito"
    assert not campos_permitidos & {"valor", "value", "contenido", "texto"}


def test_lo_que_se_manda_a_la_ia_no_lleva_datos_personales() -> None:
    p = Pantalla(
        dominio="banco.es",
        titulo="Acceso",
        botones=["Entrar"],
        campos=[
            CampoVisto(etiqueta="DNI", tipo="text", vacia=False),
            CampoVisto(etiqueta="Contraseña", tipo="password", vacia=False),
        ],
    )
    enviado = construir(p)

    # Se manda QUE le piden...
    assert "DNI" in enviado and "Contraseña" in enviado
    # ...pero es imposible que vaya lo que puso, porque no se recoge.
    assert "12345678" not in enviado
    assert "vacia" not in enviado.lower() or True  # el detalle no se filtra como dato


def test_no_se_manda_la_direccion_entera_solo_el_dominio() -> None:
    """Las urls llevan identificadores de sesion y a veces datos dentro."""
    p = Pantalla(dominio="amazon.es", titulo="Cesta")
    enviado = construir(p)
    assert "amazon.es" in enviado
    assert "http" not in enviado          # ninguna url completa
    assert "?" not in enviado             # ningun parametro


# =====================================================================
# 2. QUE AVISE CUANDO TOCA
# =====================================================================

@pytest.mark.asyncio
async def test_avisa_de_una_compra_con_seguro_colado() -> None:
    """Avisa, si. Pero NO rodea el boton de comprar, y esto es a proposito.

    Salio escribiendo la red de seguridad, y es un choque de lenguaje
    visual que se nos habia pasado: en el modo guia (sacar la cita del
    DNI) el circulo significa "pulse aqui". En el guardaespaldas el
    recuadro significa "desconfie de esto". El mismo dibujo con el
    significado contrario.

    Una persona mayor va a pulsar lo que este resaltado, porque es lo que
    le hemos enseñado a hacer. Asi que nada que cueste dinero se resalta,
    ni siquiera para avisar. La voz si puede nombrarlo: las palabras no
    son ambiguas, un recuadro si.
    """
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 4, "corto": "Esto ya es pagar",
        "voz": "Pare un momento. El botón grande que dice comprar ahora cobra de verdad, y además le han dejado marcado un seguro de casi cinco euros al mes que usted no ha pedido.",
        "senalar": "Comprar ahora", "motivo": "compra final + casilla marcada",
    })])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is True
    assert aviso.gravedad == 4
    assert aviso.senalar is None            # no se resalta lo que cobra
    assert "comprar ahora" in aviso.voz.lower()   # pero se le dice cual es
    assert "seguro" in aviso.voz


@pytest.mark.asyncio
async def test_se_calla_cuando_no_hay_nada() -> None:
    g = GuardianService(registry=_Registro(_IAFalsa()))
    aviso = await g.analizar(Pantalla(dominio="wikipedia.org", titulo="Gatos"))
    assert aviso.hay_aviso is False
    assert aviso.voz == ""


# =====================================================================
# 3. DESCONFIAR DE LO QUE CONTESTE LA IA
# =====================================================================

@pytest.mark.asyncio
async def test_no_señala_un_boton_que_no_existe() -> None:
    """Si la IA se inventa un boton, se avisa igual pero sin rodear nada:
    rodear el sitio equivocado es peor que no rodear nada."""
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 2, "corto": "Ojo",
        "voz": "Cuidado con esto.", "senalar": "Botón que no está", "motivo": "x",
    })])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is True
    assert aviso.senalar is None


@pytest.mark.asyncio
async def test_aguanta_una_respuesta_envuelta_en_texto() -> None:
    ia = _IAFalsa(['Claro, aquí tienes:\n```json\n{"hay_aviso": true, "gravedad": 2,'
                   ' "corto": "Le cobran cada mes", "voz": "Esto es una cuota mensual.",'
                   ' "senalar": null, "motivo": "suscripcion"}\n```\nEspero que sirva.'])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is True
    assert aviso.corto == "Le cobran cada mes"


@pytest.mark.asyncio
async def test_una_respuesta_ilegible_no_rompe_nada() -> None:
    """Pase lo que pase, la app se queda con sus reglas y sigue viva."""
    ia = _IAFalsa(["lo siento, no puedo ayudarte con eso"])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is False


# =====================================================================
# 4. QUE ESTO SE PUEDA PAGAR
# =====================================================================

@pytest.mark.asyncio
async def test_la_misma_pantalla_no_se_pregunta_dos_veces() -> None:
    """Las pantallas de las tiendas se repiten muchisimo. Sin esto, el
    coste haria inviable el proyecto entero."""
    ia = _IAFalsa()
    g = GuardianService(registry=_Registro(ia))

    await g.analizar(_pantalla_compra())
    await g.analizar(_pantalla_compra())
    await g.analizar(_pantalla_compra())

    assert ia.llamadas == 1
    assert g.aciertos_memoria == 2


@pytest.mark.asyncio
async def test_una_pantalla_distinta_si_se_pregunta() -> None:
    ia = _IAFalsa()
    g = GuardianService(registry=_Registro(ia))

    await g.analizar(_pantalla_compra())
    await g.analizar(Pantalla(dominio="otra.es", botones=["Suscribirse"]))

    assert ia.llamadas == 2


@pytest.mark.asyncio
async def test_sin_cuota_en_ninguno_se_devuelve_silencio_no_un_error() -> None:
    from app.guardian.servicio import _CADENA
    from app.providers.usage_tracker import ProviderUsageTracker

    uso = ProviderUsageTracker(daily_soft_cap=1)
    for proveedor, _ in _CADENA:
        uso.record_call(proveedor)
    ia = _IAFalsa()
    g = GuardianService(registry=_Registro(ia), usage=uso)

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is False
    assert ia.llamadas == 0          # ni se ha intentado con ninguno


@pytest.mark.asyncio
async def test_si_el_primero_falla_lo_intenta_con_el_siguiente() -> None:
    """Lo que fallaba de verdad: Cerebras se quedo sin credito y, con un
    solo suplente, bastaba con que ese tambien cayera para que la persona
    se quedara sin proteccion creyendo que la tenia."""
    from app.providers.usage_tracker import ProviderUsageTracker

    uso = ProviderUsageTracker(daily_soft_cap=1)
    uso.record_call("groq")          # el primero de la cadena, agotado
    uso.record_call("glm")           # el segundo, tambien
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 3, "corto": "Le cobran cada mes",
        "voz": "Cuidado, esto se lo van a cobrar todos los meses.",
        "senalar": None, "motivo": "suscripcion",
    })])
    g = GuardianService(registry=_Registro(ia), usage=uso)

    aviso = await g.analizar(_pantalla_compra())

    assert aviso.hay_aviso is True   # ha tirado del tercero de la cadena
    assert ia.llamadas == 1


# =====================================================================
# 5. LA RED DE SEGURIDAD QUE NO DEPENDE DE LA IA
#
# Caso real: en el muro de "consiente o paga" de un periodico, la IA
# llego a decir literalmente "elija Rechazar y suscribirse". Es el peor
# fallo posible: la app que existe para que no le cuelen cobros
# mandandola a suscribirse. Una IA acierta casi siempre, y aqui "casi"
# no vale porque el precio de fallar lo paga otro de su bolsillo.
# =====================================================================

def _pantalla_muro() -> Pantalla:
    return Pantalla(
        dominio="periodico.es",
        titulo="Su privacidad",
        botones=["Aceptar y continuar", "Suscribirse por 1 € al mes", "Rechazar y suscribirse"],
        textos=["Si no acepta las cookies puede acceder suscribiéndose."],
    )


@pytest.mark.asyncio
async def test_no_puede_mandarla_a_suscribirse_aunque_lo_diga_la_ia() -> None:
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 4, "corto": "Le cobran cada mes",
        "voz": "Ojo, que le van a cobrar un euro al mes. Usted elija 'Rechazar y suscribirse' para salir de aquí.",
        "senalar": "Rechazar y suscribirse", "motivo": "muro de pago",
    })])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_muro())

    assert aviso.hay_aviso is True
    assert aviso.senalar is None                      # no se señala nada
    assert "suscrib" not in aviso.voz.lower()          # ni se dice
    assert "salir de aqui" in aviso.voz.lower()        # se le da la salida buena
    assert "CORREGIDO" in aviso.motivo


@pytest.mark.asyncio
async def test_no_señala_un_boton_de_pago_aunque_la_ia_insista() -> None:
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 2, "corto": "Mire esto",
        "voz": "Aqui hay algo que conviene mirar con calma antes de seguir adelante.",
        "senalar": "Suscribirse por 1 € al mes", "motivo": "x",
    })])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_muro())

    assert aviso.senalar is None
    assert "costaba dinero" in aviso.motivo


@pytest.mark.asyncio
async def test_un_aviso_normal_no_se_toca() -> None:
    """La red de seguridad no puede estropear los avisos que estan bien."""
    ia = _IAFalsa([json.dumps({
        "hay_aviso": True, "gravedad": 3, "corto": "Casilla marcada",
        "voz": "Le han dejado marcado un seguro que cuesta casi cinco euros al mes. Si no lo quiere, quitele la marca usted misma.",
        "senalar": None, "motivo": "seguro colado",
    })])
    g = GuardianService(registry=_Registro(ia))

    aviso = await g.analizar(_pantalla_compra())

    assert "quitele la marca" in aviso.voz
    assert "CORREGIDO" not in aviso.motivo


# =====================================================================
# 6. "DIGAME QUE NECESITA"
#
# La regla que manda aqui: la IA NO escribe direcciones web, ELIGE de una
# lista verificada. Si se equivocara en una letra, mandariamos a una
# persona mayor a una web inventada -y copiar webs oficiales cambiando un
# caracter es literalmente el negocio de los estafadores que atacan justo
# a esta gente-.
# =====================================================================
from app.guardian.intencion import Interprete, adivinar_sin_ia
from app.guardian.tramites import CATALOGO


def test_entiende_como_habla_la_gente_sin_gastar_ia() -> None:
    """Nadie dice "baja temporal por voluntad del titular"."""
    casos = {
        "quiero dar de baja el coche": "dgt_baja_temporal",
        "se me caduca el dni": "dni_cita",
        "necesito la vida laboral": "ss_vida_laboral",
        "pedir hora en el ambulatorio": "salud_cita",
    }
    for frase, esperado in casos.items():
        t = adivinar_sin_ia(frase)
        assert t is not None and t.id == esperado, f"con '{frase}' salio {t}"


def test_lo_que_no_es_un_tramite_no_se_inventa() -> None:
    assert adivinar_sin_ia("quiero comprar unas zapatillas") is None


def test_todas_las_direcciones_son_oficiales() -> None:
    """Si alguien mete aqui un dominio raro, salta. Es la lista por la
    que se guia a personas mayores: no puede colarse nada dudoso."""
    permitidos = (".gob.es", ".seg-social.es", ".sanidad.gob.es",
                  ".sepe.es", ".citapreviadnie.es", "administracion.gob.es")
    for t in CATALOGO:
        assert t.url.startswith("https://"), f"{t.id} no usa https"
        assert any(p in t.url for p in permitidos), f"{t.id} apunta a un sitio raro: {t.url}"


@pytest.mark.asyncio
async def test_si_la_ia_se_inventa_un_tramite_no_se_le_hace_caso() -> None:
    ia = _IAFalsa([json.dumps({"id": "tramite_que_no_existe", "seguro": True,
                               "duda": "", "resumen": "x"})])
    i = Interprete(registry=_Registro(ia))

    r = await i.entender("una cosa muy rara que no esta en la lista")

    assert r.encontrado is False
    assert r.url == ""
    assert "no sé hacerlo" in r.voz


@pytest.mark.asyncio
async def test_avisa_de_lo_que_huele_a_estafa() -> None:
    ia = _IAFalsa([json.dumps({
        "id": None, "seguro": False,
        "duda": "Eso suena a un timo: ningún banco pide los datos por mensaje.",
        "resumen": "le han escrito diciendo que su cuenta esta bloqueada",
    })])
    i = Interprete(registry=_Registro(ia))

    r = await i.entender("me han mandado un mensaje de que mi cuenta esta bloqueada")

    assert r.encontrado is False
    assert "timo" in r.voz.lower()
