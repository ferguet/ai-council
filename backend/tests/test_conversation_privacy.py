"""
Cada visitante tiene sus propias salas y no puede ver ni tocar las de
los demas (ver app/core/access.py y el scoping en ConversationEngine).
"""
from __future__ import annotations

import pytest

from app.conversation.engine import ConversationEngine
from app.domain.conversation_models import ConversationKind, Participant


class _FakeBus:
    async def publish(self, event) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.saved = None

    async def save(self, conversations) -> None:
        self.saved = conversations

    async def close(self) -> None:
        pass


class _FakeRegistry:
    def get(self, name: str):
        raise AssertionError("no deberia hacer falta un proveedor real en estos tests")


def _roster() -> dict[str, Participant]:
    return {
        "mistral": Participant(
            id="mistral", name="Mistral", provider="mistral", model="m",
            system_prompt="eres mistral", avatar="M", color="#fff",
        ),
    }


def _engine() -> ConversationEngine:
    return ConversationEngine(
        conversations={}, roster=_roster(), registry=_FakeRegistry(),
        event_bus=_FakeBus(), store=_FakeStore(),
    )


def test_each_visitor_gets_their_own_default_room() -> None:
    eng = _engine()
    conv_a = eng.ensure_default_conversation("visitor-a")
    conv_b = eng.ensure_default_conversation("visitor-b")

    assert conv_a.id != conv_b.id
    assert conv_a.owner_visitor_id == "visitor-a"
    assert conv_b.owner_visitor_id == "visitor-b"
    # ambas salas nacen con el mismo roster real, pero son objetos distintos
    assert conv_a.participant_ids == conv_b.participant_ids == ["mistral"]


def test_list_summaries_only_shows_own_rooms() -> None:
    eng = _engine()
    eng.ensure_default_conversation("visitor-a")
    eng.ensure_default_conversation("visitor-b")
    eng.create_conversation("Extra de A", ["mistral"], ConversationKind.GROUP, owner_visitor_id="visitor-a")

    summaries_a = eng.list_summaries("visitor-a")
    summaries_b = eng.list_summaries("visitor-b")

    assert len(summaries_a) == 2
    assert len(summaries_b) == 1
    assert {s["id"] for s in summaries_a}.isdisjoint({s["id"] for s in summaries_b})


def test_get_owned_refuses_other_visitors_room() -> None:
    eng = _engine()
    conv_a = eng.ensure_default_conversation("visitor-a")

    assert eng.get_owned(conv_a.id, "visitor-a") is conv_a
    assert eng.get_owned(conv_a.id, "visitor-b") is None
    assert eng.get_owned("no-existe", "visitor-a") is None
    # get() sin scope si sigue funcionando (lo usan las rutas ya autorizadas)
    assert eng.get(conv_a.id) is conv_a


@pytest.mark.asyncio
async def test_kick_and_invite_are_scoped_to_owner() -> None:
    eng = _engine()
    conv_a = eng.ensure_default_conversation("visitor-a")

    with pytest.raises(KeyError):
        await eng.kick(conv_a.id, "mistral", "visitor-b")
    with pytest.raises(KeyError):
        await eng.invite(conv_a.id, "mistral", "visitor-b")

    # el dueno real si puede
    await eng.kick(conv_a.id, "mistral", "visitor-a")
    assert "mistral" in conv_a.excluded_ids
    await eng.invite(conv_a.id, "mistral", "visitor-a")
    assert "mistral" not in conv_a.excluded_ids


def test_snapshot_and_send_do_not_require_visitor_but_id_must_exist() -> None:
    """snapshot()/send_user_message() no re-comprueban propiedad (ya la
    comprueba la ruta que llama antes), pero si deben seguir fallando con
    KeyError si la sala directamente no existe."""
    eng = _engine()
    with pytest.raises(KeyError):
        eng.snapshot("no-existe")


@pytest.mark.asyncio
async def test_request_claude_intervention_posts_a_marker_without_ai_replies() -> None:
    """El boton "Llamar a Claude" deja un mensaje marcado en el chat pero
    NO debe llamar a ningun proveedor real (usa _FakeRegistry, que revienta
    si algo la invoca): confirma que no dispara _generate_replies."""
    eng = _engine()
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.request_claude_intervention(conv.id)

    assert len(conv.messages) == 1
    marker = conv.messages[0]
    assert marker.sender_id == "claude_call"
    assert "Claude" in marker.content


@pytest.mark.asyncio
async def test_request_claude_intervention_raises_for_unknown_conversation() -> None:
    eng = _engine()
    with pytest.raises(KeyError):
        await eng.request_claude_intervention("no-existe")
