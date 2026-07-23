"""
Proveedor simulado: no llama a ninguna API externa. Existe para poder
probar el sistema completo (orquestador, director, streaming, frontend)
sin gastar dinero ni necesitar ninguna clave. Tambien lo usan los tests.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from typing import AsyncIterator

from app.providers.base import AIProvider, ChatMessage

_STANCES = [
    "Creo que la evidencia disponible apunta a que {topic} merece la pena, "
    "aunque con matices importantes que deberiamos revisar.",
    "No estoy de acuerdo con el planteamiento anterior. Sobre {topic}, "
    "los riesgos superan a los beneficios si no se acota mejor el alcance.",
    "Buena observacion. Anadiria un matiz: {topic} depende mucho del contexto "
    "y de los datos concretos que estemos usando.",
    "Pido pruebas de esa afirmacion. ¿En que datos concretos se basa la postura "
    "sobre {topic}?",
    "Creo que hay consenso emergente: {topic} es viable si se limita el alcance "
    "y se define bien la metrica de exito.",
]


class MockProvider(AIProvider):
    name = "mock"

    def is_configured(self) -> bool:
        return True  # siempre disponible

    @staticmethod
    def _extract_topic_hint(messages: list[ChatMessage]) -> str:
        """
        messages[0] siempre es el system prompt (personalidad del agente o del
        Director), no el tema. Buscamos el tema real en el primer mensaje de
        usuario, que en este sistema siempre empieza con 'Tema del debate:'.
        """
        for m in messages:
            if "Tema del debate:" in m.content:
                after = m.content.split("Tema del debate:", 1)[1]
                return after.split("\n", 1)[0].strip()
        for m in messages:
            if m.role == "user":
                return m.content
        return "el tema"

    def _pick_response(self, messages: list[ChatMessage]) -> str:
        topic_hint = self._extract_topic_hint(messages)
        seed = int(hashlib.sha256(topic_hint.encode()).hexdigest(), 16)
        rng = random.Random(seed + len(messages))
        template = rng.choice(_STANCES)
        return template.format(topic=topic_hint[:60])

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        await asyncio.sleep(0.2)
        return self._pick_response(messages)

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        text = self._pick_response(messages)
        for word in text.split(" "):
            await asyncio.sleep(0.04)
            yield word + " "
