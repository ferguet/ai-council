"""
El servicio del Guardian: coge una pantalla, se la enseña a una IA y
devuelve el aviso, si lo hay.

Tres cosas que condicionan todo el diseño:

1. LA PERSONA NO PUEDE ESPERAR. Un mayor mirando una pantalla parada
   cinco segundos se pone nervioso y se sale. Por eso en la app las
   reglas de siempre siguen contestando al instante y esto llega
   despues, para afinar. La IA no sustituye a las reglas: las mejora.

2. CADA PANTALLA CUESTA DINERO. Si se llamase en cada pagina que abre,
   esto no se sostiene. De ahi la memoria de abajo: dos pantallas con la
   misma estructura tienen la misma respuesta, y la segunda es gratis.

3. SI ESTO FALLA, NO PASA NADA. Si no hay cuota, si la IA tarda o si
   contesta cualquier cosa, se devuelve "no hay aviso" y la app sigue
   funcionando con sus reglas. Nunca se queda tirada.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict

from app.guardian.models import Aviso, Pantalla
from app.guardian.prompt import INSTRUCCIONES, construir
from app.providers.base import ChatMessage, ProviderError
from app.providers.circuit_breaker import ProviderCircuitBreaker
from app.providers.usage_tracker import ProviderUsageTracker

# Modelo barato y rapido a proposito: aqui no hace falta un genio, hace
# falta alguien espabilado que conteste en un segundo. Y como el volumen
# puede ser alto, el precio manda.
_PROVEEDOR = "cerebras"
_MODELO = "gpt-oss-120b"
_RESPALDO = ("groq", "llama-3.3-70b-versatile")

_MAX_MEMORIA = 400


class GuardianService:
    def __init__(
        self,
        registry,
        breaker: ProviderCircuitBreaker | None = None,
        usage: ProviderUsageTracker | None = None,
        proveedor: str = _PROVEEDOR,
        modelo: str = _MODELO,
    ) -> None:
        self._registry = registry
        self._breaker = breaker or ProviderCircuitBreaker()
        self._usage = usage or ProviderUsageTracker()
        self._proveedor = proveedor
        self._modelo = modelo
        # Memoria de pantallas ya vistas. Es lo que hace esto viable:
        # las pantallas de las tiendas se repiten muchisimo entre
        # personas distintas, asi que la mayoria de las consultas ni
        # llegan a la IA.
        self._memoria: OrderedDict[str, Aviso] = OrderedDict()
        self.consultas = 0
        self.aciertos_memoria = 0
        # Diario de lo ultimo que ha pasado. Sin esto era imposible
        # distinguir "he preguntado y no hay peligro" de "no he podido
        # preguntar": las dos cosas acababan en un silencio identico, y
        # se arreglan de forma muy distinta.
        self.diario: list[str] = []

    def _apuntar(self, texto: str) -> None:
        self.diario.append(texto)
        if len(self.diario) > 20:
            self.diario = self.diario[-20:]

    @staticmethod
    def _huella(p: Pantalla) -> str:
        """Identifica una pantalla por su forma, no por su contenido."""
        crudo = json.dumps(
            {
                "d": p.dominio,
                "b": sorted(p.botones)[:20],
                "c": sorted(c.etiqueta + str(c.marcada) for c in p.campos)[:15],
                "e": sorted(p.encabezados)[:6],
            },
            ensure_ascii=False,
        )
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:20]

    async def analizar(self, p: Pantalla) -> Aviso:
        self.consultas += 1

        huella = self._huella(p)
        if huella in self._memoria:
            self.aciertos_memoria += 1
            self._memoria.move_to_end(huella)
            return self._memoria[huella]

        aviso = await self._preguntar(self._proveedor, self._modelo, p)
        if aviso is None:
            aviso = await self._preguntar(_RESPALDO[0], _RESPALDO[1], p)
        if aviso is None:
            # Sin cuota o sin respuesta: la app se queda con sus reglas.
            return Aviso(motivo="no se pudo consultar")

        self._memoria[huella] = aviso
        while len(self._memoria) > _MAX_MEMORIA:
            self._memoria.popitem(last=False)
        return aviso

    async def _preguntar(self, proveedor: str, modelo: str, p: Pantalla) -> Aviso | None:
        if self._breaker.is_open(proveedor):
            self._apuntar(f"{proveedor}: en pausa por fallos anteriores")
            return None
        if self._usage.is_near_limit(proveedor):
            self._apuntar(f"{proveedor}: cuota diaria agotada")
            return None
        try:
            cliente = self._registry.get(proveedor)
        except Exception as e:
            self._apuntar(f"{proveedor}: no existe ese proveedor ({e})")
            return None
        if not cliente.is_configured():
            self._apuntar(f"{proveedor}: SIN CLAVE configurada en el servidor")
            return None

        mensajes = [
            ChatMessage(role="system", content=INSTRUCCIONES),
            ChatMessage(role="user", content=construir(p)),
        ]
        self._usage.record_call(proveedor)
        try:
            crudo = await cliente.chat(mensajes, model=modelo, temperature=0.2)
            self._breaker.record_success(proveedor)
        except ProviderError as e:
            self._breaker.record_failure(proveedor)
            self._apuntar(f"{proveedor}: error del proveedor -> {str(e)[:180]}")
            return None
        except Exception as e:
            self._breaker.record_failure(proveedor)
            self._apuntar(f"{proveedor}: fallo inesperado -> {type(e).__name__}: {str(e)[:150]}")
            return None

        aviso = self._interpretar(crudo, p)
        if aviso is None:
            self._apuntar(f"{proveedor}: contesto algo que no entiendo -> {(crudo or '')[:180]}")
        else:
            self._apuntar(f"{proveedor}: OK, aviso={aviso.hay_aviso} ({aviso.corto or aviso.motivo})")
        return aviso

    @staticmethod
    def _interpretar(crudo: str, p: Pantalla) -> Aviso | None:
        """Saca el JSON de la respuesta y lo comprueba.

        Se desconfia de lo que conteste la IA: puede envolverlo en texto,
        inventarse un boton que no existe o pasarse de largo. Todo eso se
        corrige aqui, no en el movil de la señora.
        """
        m = re.search(r"\{.*\}", crudo or "", re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

        if not d.get("hay_aviso"):
            return Aviso(motivo=str(d.get("motivo", ""))[:200])

        senalar = d.get("senalar")
        # Solo vale señalar un boton que EXISTA de verdad en la pantalla.
        # Si se inventa uno, se avisa igual pero sin rodear nada.
        if senalar and senalar not in p.botones:
            senalar = next((b for b in p.botones if b.strip().lower() == str(senalar).strip().lower()), None)

        return Aviso(
            hay_aviso=True,
            gravedad=max(0, min(4, int(d.get("gravedad", 1) or 1))),
            corto=str(d.get("corto", ""))[:40],
            voz=str(d.get("voz", ""))[:700],
            senalar=senalar,
            motivo=str(d.get("motivo", ""))[:200],
        )
