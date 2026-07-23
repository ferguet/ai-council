"""
Stub para OpenAI. Requiere pago (tras el credito inicial de prueba), por eso
no es uno de los proveedores por defecto del MVP, pero la interfaz esta lista:
en cuanto tengas la key, activarlo es implementar estos dos metodos siguiendo
exactamente el mismo patron que app/providers/groq_provider.py (la API de
OpenAI y la de Groq son compatibles), y registrarlo en providers/registry.py.
"""
from __future__ import annotations

from typing import AsyncIterator

from app.providers.base import AIProvider, ChatMessage, ProviderError

_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        raise ProviderError(
            "OpenAIProvider es un stub. Implementa este metodo igual que "
            "GroqProvider.chat (la API es compatible) cuando tengas la key."
        )

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        raise ProviderError(
            "OpenAIProvider es un stub. Implementa este metodo igual que "
            "GroqProvider.stream_chat (la API es compatible) cuando tengas la key."
        )
        yield ""  # pragma: no cover
