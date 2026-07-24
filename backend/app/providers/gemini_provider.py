"""
Proveedor para Google Gemini via la API de Google AI Studio (nivel gratuito).

Doc: https://ai.google.dev/api/generate-content
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.providers.base import AIProvider, ChatMessage, ProviderError

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _to_gemini_payload(messages: list[ChatMessage]) -> dict:
        # Gemini separa el system prompt del resto del historial.
        system_parts = [m.content for m in messages if m.role == "system"]

        def _parts(m: ChatMessage) -> list[dict]:
            parts: list[dict] = []
            if m.content:
                parts.append({"text": m.content})
            if m.image_base64:
                parts.append({
                    "inlineData": {"mimeType": m.image_mime or "image/jpeg", "data": m.image_base64},
                })
            return parts or [{"text": " "}]

        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": _parts(m),
            }
            for m in messages
            if m.role != "system"
        ]
        if contents:
            payload: dict = {"contents": contents}
            if system_parts:
                payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        else:
            # En este proyecto, los turnos de agente a veces solo llevan un
            # mensaje "system" (persona + contexto + instrucciones), sin
            # mensaje de usuario separado. Gemini exige que "contents" no
            # este vacio, asi que lo usamos como el unico turno.
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": "\n\n".join(system_parts) or " "}]}
                ]
            }
        return payload

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        if not self._api_key:
            raise ProviderError("GEMINI_API_KEY no configurada")
        url = f"{_BASE_URL}/{model}:generateContent"
        payload = self._to_gemini_payload(messages)
        payload["generationConfig"] = {"temperature": temperature}
        headers = {"x-goog-api-key": self._api_key}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise ProviderError(f"Gemini error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Respuesta inesperada de Gemini: {data}") from exc

    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise ProviderError("GEMINI_API_KEY no configurada")
        url = f"{_BASE_URL}/{model}:streamGenerateContent?alt=sse"
        payload = self._to_gemini_payload(messages)
        payload["generationConfig"] = {"temperature": temperature}
        headers = {"x-goog-api-key": self._api_key}
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise ProviderError(f"Gemini error {resp.status_code}: {body[:300]!r}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        data = json.loads(chunk)
                        text = data["candidates"][0]["content"]["parts"][0]["text"]
                        yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
