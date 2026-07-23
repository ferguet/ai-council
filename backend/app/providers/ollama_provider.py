"""
Proveedor para Ollama: modelos corriendo en local, gratis e ilimitados.
No requiere API key, solo tener Ollama instalado y arrancado (ollama.com).

Doc: https://github.com/ollama/ollama/blob/main/docs/api.md
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.providers.base import AIProvider, ChatMessage, ProviderError


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def is_configured(self) -> bool:
        # No podemos saber si Ollama esta corriendo sin hacer una llamada de red;
        # asumimos que si el usuario lo configuro, quiere intentarlo.
        return bool(self._base_url)

    @staticmethod
    def _to_ollama_messages(messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        payload = {
            "model": model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise ProviderError(
                "No se pudo conectar con Ollama. ¿Esta corriendo en tu maquina? (ollama serve)"
            ) from exc
        if resp.status_code != 200:
            raise ProviderError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["message"]["content"]

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": self._to_ollama_messages(messages),
            "stream": True,
            "options": {"temperature": temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise ProviderError(f"Ollama error {resp.status_code}: {body[:300]!r}")
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError as exc:
            raise ProviderError(
                "No se pudo conectar con Ollama. ¿Esta corriendo en tu maquina? (ollama serve)"
            ) from exc
