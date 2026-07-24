"""
Adjuntos con vision real: una imagen subida al Chat Grupal debe llegar
codificada en base64 hasta el ChatMessage que ve Gemini (unico proveedor
con vision implementada), y los proveedores sin vision deben poder seguir
ignorando esos campos sin romperse.
"""
from __future__ import annotations

import base64

import pytest

from app.conversation.attachments import extract_image
from app.conversation.engine import ConversationEngine
from app.domain.conversation_models import Participant
from app.providers.base import ChatMessage
from app.providers.gemini_provider import GeminiProvider


def test_extract_image_recognizes_supported_formats():
    fake_png = b"\x89PNG\r\n\x1a\nfake-bytes"
    result = extract_image("foto.png", fake_png)
    assert result is not None
    b64, mime = result
    assert mime == "image/png"
    assert base64.b64decode(b64) == fake_png


def test_extract_image_returns_none_for_non_image():
    assert extract_image("informe.pdf", b"%PDF-1.4 ...") is None


def test_extract_image_returns_none_when_too_big(monkeypatch):
    import app.conversation.attachments as mod
    monkeypatch.setattr(mod, "_MAX_IMAGE_BYTES", 10)
    assert extract_image("foto.jpg", b"x" * 100) is None


def test_gemini_payload_embeds_inline_image():
    messages = [
        ChatMessage(role="system", content="eres una IA con vision"),
        ChatMessage(role="user", content="que ves aqui?", image_base64="ZmFrZQ==", image_mime="image/png"),
    ]
    payload = GeminiProvider._to_gemini_payload(messages)
    parts = payload["contents"][0]["parts"]
    assert {"text": "que ves aqui?"} in parts
    assert {"inlineData": {"mimeType": "image/png", "data": "ZmFrZQ=="}} in parts


def test_gemini_payload_without_image_has_no_inline_data():
    messages = [ChatMessage(role="user", content="hola")]
    payload = GeminiProvider._to_gemini_payload(messages)
    parts = payload["contents"][0]["parts"]
    assert all("inlineData" not in p for p in parts)


class _FakeBus:
    async def publish(self, event) -> None:
        pass


class _FakeStore:
    async def save(self, conversations) -> None:
        pass

    async def close(self) -> None:
        pass


class _RecordingProvider:
    def __init__(self) -> None:
        self.seen_images: list[tuple[str | None, str | None]] = []

    async def chat(self, messages, model, temperature=0.9) -> str:
        last = messages[-1]
        self.seen_images.append((last.image_base64, last.image_mime))
        return "veo una grafica de barras"


class _FakeRegistry:
    def __init__(self, provider) -> None:
        self._provider = provider

    def get(self, name: str):
        return self._provider


@pytest.mark.asyncio
async def test_send_attachment_image_reaches_provider_as_chat_message():
    roster = {
        "gemini": Participant(
            id="gemini", name="Gemini", provider="gemini", model="g",
            system_prompt="eres gemini", avatar="G", color="#fff",
        ),
    }
    provider = _RecordingProvider()
    eng = ConversationEngine(
        conversations={}, roster=roster, registry=_FakeRegistry(provider),
        event_bus=_FakeBus(), store=_FakeStore(),
    )
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_attachment(
        conv.id, filename="grafico.png", size_bytes=123, kind="image",
        extracted_text=None, caption="que ves?", image_base64="ZmFrZQ==", image_mime="image/png",
    )

    # el ultimo ChatMessage que vio el proveedor (el propio adjunto, ya que
    # es el mas reciente del historial) debe llevar la imagen colgada
    assert provider.seen_images[-1] == ("ZmFrZQ==", "image/png")

    reply = next(m for m in conv.messages if m.sender_id == "gemini")
    assert reply.content == "veo una grafica de barras"

    # el payload que iria al frontend no debe filtrar el base64 completo,
    # solo una data_url servida para pintar la miniatura (comportamiento
    # esperado, no un fallo de privacidad: es la misma imagen que subio el
    # propio usuario a esa sala).
    payload = eng._message_payload(conv.messages[0])
    assert payload["attachment"]["data_url"] == "data:image/png;base64,ZmFrZQ=="
