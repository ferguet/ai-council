"""
Proveedor para NVIDIA NIM (API catalog de NVIDIA, +100 modelos hospedados).
API compatible con el formato OpenAI. Acceso gratis de prueba/prototipado
al unirte al programa de desarrollador de NVIDIA, sin tarjeta.

Cuenta gratis en https://build.nvidia.com (login con email).
Doc: https://docs.api.nvidia.com/nim/reference/llm-apis
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.providers.base import AIProvider, ChatMessage, ProviderError

_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


class NvidiaProvider(AIProvider):
    name = "nvidia"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _to_openai_messages(messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        if not self._api_key:
            raise ProviderError("NVIDIA_API_KEY no configurada")
        payload = {
            "model": model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(_URL, headers=self._headers(), json=payload)
        if resp.status_code != 200:
            raise ProviderError(f"NVIDIA error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise ProviderError("NVIDIA_API_KEY no configurada")
        payload = {
            "model": model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", _URL, headers=self._headers(), json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise ProviderError(f"NVIDIA error {resp.status_code}: {body[:300]!r}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
