"""
Entender que quiere hacer la persona, dicho con sus palabras.

Es la vuelta de tortilla del proyecto. Hasta ahora la app miraba la
pantalla y avisaba; era util pero pasiva, y no resolvia el problema de
fondo: que no saben ni por donde empezar. Nadie sabe que "dar de baja el
coche" se llama oficialmente "baja temporal por voluntad del titular",
ni en que web se hace.

Aqui la persona dice "quiero quitar el coche de la circulacion" y esto
decide de que tramite habla, de la lista verificada. Nunca inventa una
direccion: ver el porque en tramites.py.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel

from app.guardian.tramites import CATALOGO, Tramite, buscar, resumen_para_ia
from app.providers.base import ChatMessage, ProviderError

INSTRUCCIONES = """Ayudas a personas mayores españolas a hacer papeleo por internet.

Te van a decir con sus palabras qué necesitan. Suelen hablar como en la vida real: "se me caduca el carnet", "quiero quitar el coche de en medio", "a ver cuánto voy a cobrar de pensión". Casi nunca usan el nombre oficial del trámite.

Tu trabajo es decidir CUÁL de estos trámites es. Solo puedes elegir uno de la lista, por su identificador:

{lista}

REGLAS
- Si encaja claramente con uno, devuélvelo.
- Si podría ser dos cosas distintas, elige el más probable y di en "duda" qué habría que preguntarle.
- Si NO está en la lista, devuelve id null. No te inventes nada: es preferible decirle "esto no lo tengo" que mandarla a un sitio equivocado.
- Si lo que cuenta suena a estafa (le han llamado, le han mandado un mensaje diciendo que su cuenta está bloqueada, le piden datos del banco), devuelve id null y avisa de eso en "duda".

CONTESTA SOLO CON UN JSON:
{{"id": "identificador_de_la_lista_o_null",
  "seguro": true/false,
  "duda": "qué le preguntarías si no está claro, o el aviso si huele a timo",
  "resumen": "lo que ha entendido que quiere, en una frase corta y con sus palabras"}}
"""


class Respuesta(BaseModel):
    encontrado: bool = False
    id: str | None = None
    nombre: str = ""
    organismo: str = ""
    url: str = ""
    lleva: list[str] = []
    ojo: str = ""
    voz: str = ""            # lo que se le dice en alto
    duda: str = ""


def _sin_tildes(t: str) -> str:
    for a, b in zip("áéíóúüñ", "aeiouun"):
        t = t.replace(a, b)
    return t


def adivinar_sin_ia(texto: str) -> Tramite | None:
    """Primero se intenta sin gastar una llamada.

    Muchas peticiones son literalmente una de las frases que ya tenemos
    apuntadas ("renovar el dni", "vida laboral"). Resolverlas aqui es
    instantaneo y gratis, y ademas funciona sin cobertura.
    """
    t = _sin_tildes(texto.lower())
    mejor, puntos = None, 0
    for tr in CATALOGO:
        for alias in tr.tambien + [tr.nombre]:
            a = _sin_tildes(alias.lower())
            if a in t:
                if len(a) > puntos:
                    mejor, puntos = tr, len(a)
    return mejor


def _voz_de(tr: Tramite) -> str:
    partes = [f"Muy bien. Vamos a {tr.nombre.lower()}. Esto se hace en {tr.organismo}."]
    if tr.lleva:
        partes.append("Antes de empezar, tenga a mano: " + ", ".join(tr.lleva) + ".")
    if tr.ojo:
        partes.append(tr.ojo)
    partes.append("Le llevo a la página y le voy diciendo dónde tocar.")
    return " ".join(partes)


def respuesta_de(tr: Tramite, duda: str = "") -> Respuesta:
    return Respuesta(
        encontrado=True, id=tr.id, nombre=tr.nombre, organismo=tr.organismo,
        url=tr.url, lleva=tr.lleva, ojo=tr.ojo, voz=_voz_de(tr), duda=duda,
    )


NO_LO_TENGO = Respuesta(
    encontrado=False,
    voz="Perdone, pero eso no sé hacerlo todavía. Prefiero decírselo a mandarle "
        "a un sitio equivocado. Si quiere, pruebe a decírmelo de otra manera.",
)


class Interprete:
    def __init__(self, registry, breaker=None, usage=None, cadena=None) -> None:
        from app.guardian.servicio import _CADENA
        from app.providers.circuit_breaker import ProviderCircuitBreaker
        from app.providers.usage_tracker import ProviderUsageTracker

        self._registry = registry
        self._breaker = breaker or ProviderCircuitBreaker()
        self._usage = usage or ProviderUsageTracker()
        self._cadena = cadena or _CADENA
        self.diario: list[str] = []

    async def entender(self, texto: str) -> Respuesta:
        texto = (texto or "").strip()[:300]
        if not texto:
            return NO_LO_TENGO

        # 1. A ver si se resuelve solo, sin gastar nada
        directo = adivinar_sin_ia(texto)
        if directo is not None:
            self.diario.append(f"resuelto sin IA -> {directo.id}")
            return respuesta_de(directo)

        # 2. Si no, se pregunta a la IA (que solo puede ELEGIR de la lista)
        for proveedor, modelo in self._cadena:
            if self._breaker.is_open(proveedor) or self._usage.is_near_limit(proveedor):
                continue
            try:
                cliente = self._registry.get(proveedor)
                if not cliente.is_configured():
                    continue
            except Exception:
                continue

            self._usage.record_call(proveedor)
            try:
                crudo = await cliente.chat(
                    [
                        ChatMessage(role="system",
                                    content=INSTRUCCIONES.format(lista=resumen_para_ia())),
                        ChatMessage(role="user", content=texto),
                    ],
                    model=modelo, temperature=0.1,
                )
                self._breaker.record_success(proveedor)
            except (ProviderError, Exception) as e:
                self._breaker.record_failure(proveedor)
                self.diario.append(f"{proveedor}: {type(e).__name__} {str(e)[:100]}")
                continue

            m = re.search(r"\{.*\}", crudo or "", re.S)
            if not m:
                self.diario.append(f"{proveedor}: no devolvio JSON")
                continue
            try:
                d = json.loads(m.group(0))
            except json.JSONDecodeError:
                self.diario.append(f"{proveedor}: JSON roto")
                continue

            tr = buscar(str(d.get("id") or ""))
            self.diario.append(f"{proveedor}: eligio {d.get('id')}")
            if tr is None:
                r = NO_LO_TENGO.model_copy()
                r.duda = str(d.get("duda", ""))[:300]
                if r.duda:
                    r.voz = r.voz + " " + r.duda
                return r
            return respuesta_de(tr, duda=str(d.get("duda", ""))[:300])

        self.diario.append("ningun proveedor disponible")
        return NO_LO_TENGO
