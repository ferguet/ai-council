"""
Proveedor para Anthropic (Claude). De pago (no hay nivel gratuito real de
API), pensado para el rol de "Profesora": una IA potente dedicada a
resolver las dudas y curiosidades del resto de ciudadanos.

La API de Anthropic no es compatible con el formato OpenAI: usa el header
"x-api-key" (no "Authorization: Bearer"), un header extra "anthropic-version",
y el system prompt va en un campo "system" separado en vez de ir dentro de
la lista de mensajes. Doc: https://docs.anthropic.com/en/api/messages
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.providers.base import AIProvider, ChatMessage, ProviderError

_URL = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"
_MAX_TOKENS = 1024


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict:
        return {
            "x-api-key": self._api_key or "",
            "anthropic-version": _VERSION,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        """Anthropic quiere el system prompt aparte, no como un mensaje mas.
        Si hay varios mensajes 'system' (no deberia pasar, pero por si acaso)
        se concatenan; el resto se mapea a user/assistant tal cual."""
        system_parts = [m.content for m in messages if m.role == "system"]
        rest = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        if not rest:
            rest = [{"role": "user", "content": "(sin mensaje)"}]
        return "\n\n".join(system_parts), rest

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        if not self._api_key:
            raise ProviderError("ANTHROPIC_API_KEY no configurada")
        system, rest = self._split_system(messages)
        payload = {
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "temperature": temperature,
            "messages": rest,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(_URL, headers=self._headers(), json=payload)
        if resp.status_code != 200:
            raise ProviderError(f"Anthropic error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        parts = data.get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if not text:
            raise ProviderError(f"Anthropic devolvio una respuesta sin texto: {data}")
        return text

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise ProviderError("ANTHROPIC_API_KEY no configurada")
        system, rest = self._split_system(messages)
        payload = {
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "temperature": temperature,
            "messages": rest,
            "stream": True,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", _URL, headers=self._headers(), json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise ProviderError(f"Anthropic error {resp.status_code}: {body[:300]!r}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if not chunk:
                        continue
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "content_block_delta":
                        delta = data.get("delta", {}).get("text")
                        if delta:
                            yield delta
