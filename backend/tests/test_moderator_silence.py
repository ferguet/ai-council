"""
El Moderador no debe llenar la sala hablando en cada mensaje: si decide que
no hace falta intervenir, contesta con el token de silencio y ese turno no
se debe publicar como mensaje (ver MODERATOR_ID/_SILENCE_TOKEN en
app/conversation/engine.py).
"""
from __future__ import annotations

import pytest

from app.conversation.engine import ConversationEngine, MODERATOR_ID
from app.domain.conversation_models import Participant
from app.providers.base import ChatMessage


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event) -> None:
        self.published.append(event)


class _FakeStore:
    async def save(self, conversations) -> None:
        pass

    async def close(self) -> None:
        pass


class _ScriptedProvider:
    """Devuelve, en orden, las respuestas programadas para cada llamada."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.9) -> str:
        return self._replies.pop(0)


class _FakeRegistry:
    def __init__(self, providers: dict[str, object]) -> None:
        self._providers = providers

    def get(self, name: str):
        return self._providers[name]


def _roster() -> dict[str, Participant]:
    return {
        "mistral": Participant(
            id="mistral", name="Mistral", provider="mistral", model="m",
            system_prompt="eres mistral", avatar="M", color="#fff",
        ),
        MODERATOR_ID: Participant(
            id=MODERATOR_ID, name="Moderador", provider="gemini2", model="g",
            system_prompt="eres el moderador", avatar="🕊️", color="#5EC9B3",
        ),
    }


@pytest.mark.asyncio
async def test_moderator_silence_token_is_not_published() -> None:
    registry = _FakeRegistry({
        "mistral": _ScriptedProvider(["Hola, todo bien por aqui."]),
        "gemini2": _ScriptedProvider(["[SIN INTERVENIR]"]),
    })
    bus = _FakeBus()
    eng = ConversationEngine(
        conversations={}, roster=_roster(), registry=registry,
        event_bus=bus, store=_FakeStore(),
    )
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "Hola a todos")

    senders = [m.sender_id for m in conv.messages]
    assert "user" in senders
    assert "mistral" in senders
    assert MODERATOR_ID not in senders  # se quedo callado, no publico nada


@pytest.mark.asyncio
async def test_moderator_speaks_when_it_decides_to() -> None:
    registry = _FakeRegistry({
        "mistral": _ScriptedProvider(["Que exagerada eres, Nvidia."]),
        "gemini2": _ScriptedProvider(["Vale, bajad el tono los dos."]),
    })
    bus = _FakeBus()
    eng = ConversationEngine(
        conversations={}, roster=_roster(), registry=registry,
        event_bus=bus, store=_FakeStore(),
    )
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "Esto se esta poniendo tenso")

    senders = [m.sender_id for m in conv.messages]
    assert MODERATOR_ID in senders
    mod_msg = next(m for m in conv.messages if m.sender_id == MODERATOR_ID)
    assert mod_msg.content == "Vale, bajad el tono los dos."
