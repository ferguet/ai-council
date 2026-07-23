"""
Stub para Anthropic (Claude). Igual que openai_provider.py: de pago tras el
credito inicial, interfaz lista para cuando quieras activarlo. La API de
Anthropic usa el header "x-api-key" y el endpoint /v1/messages, no es
compatible con el formato OpenAI, asi que al implementarlo hay que adaptar
el payload (ver https://docs.anthropic.com/en/api/messages).
"""
from __future__ import annotations

from typing import AsyncIterator

from app.providers.base import AIProvider, ChatMessage, ProviderError


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        raise ProviderError(
            "AnthropicProvider es un stub. Implementa contra POST "
            "https://api.anthropic.com/v1/messages con header x-api-key "
            "cuando tengas la key."
        )

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        raise ProviderError(
            "AnthropicProvider es un stub. Implementa streaming SSE contra "
            "/v1/messages con stream=true cuando tengas la key."
        )
        yield ""  # pragma: no cover
