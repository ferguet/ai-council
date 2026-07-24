"""
Resiliencia del Chat Grupal ante fallos de proveedor: circuit breaker (no
seguir golpeando un proveedor caido cada ronda) y proveedor de respaldo por
ciudadano (no perder el turno entero si hay alternativa configurada).

Idea original de la ciudadana "Kimi" en el propio Chat Grupal (24/07),
motivada por los 429 de cuota agotada de Gemini en Profesora/Moderador.
"""
from __future__ import annotations

import pytest

from app.conversation.engine import ConversationEngine
from app.domain.conversation_models import Participant
from app.providers.base import AIProvider, ChatMessage, ProviderError
from app.providers.circuit_breaker import ProviderCircuitBreaker


class _FakeBus:
    async def publish(self, event) -> None:
        pass


class _FakeStore:
    async def save(self, conversations) -> None:
        pass

    async def close(self) -> None:
        pass


class _CountingProvider(AIProvider):
    """Cuenta cuantas veces se le llama de verdad, para poder comprobar que
    el circuit breaker deja de invocar al proveedor cuando esta abierto (en
    vez de solo confiar en que "parece" que no se llamo)."""

    def __init__(self, name: str, fail: bool = True, response: str = "ok") -> None:
        self.name = name
        self.calls = 0
        self._fail = fail
        self._response = response

    def is_configured(self) -> bool:
        return True

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        self.calls += 1
        if self._fail:
            raise ProviderError("fallo simulado")
        return self._response

    async def stream_chat(self, messages, model, temperature=0.7):
        raise ProviderError("no usado en este test")
        yield ""  # pragma: no cover


class _NamedRegistry:
    def __init__(self, providers: dict[str, AIProvider]) -> None:
        self._providers = providers

    def get(self, name: str) -> AIProvider:
        return self._providers[name]


def _roster_with_gemini_citizen() -> dict[str, Participant]:
    return {
        "gemini": Participant(
            id="gemini", name="Gemini", provider="gemini", model="gemini-3.6-flash",
            system_prompt="eres gemini", avatar="G", color="#fff",
        ),
    }


def _engine(registry: _NamedRegistry, breaker: ProviderCircuitBreaker | None = None) -> ConversationEngine:
    return ConversationEngine(
        conversations={}, roster=_roster_with_gemini_citizen(), registry=registry,
        event_bus=_FakeBus(), store=_FakeStore(), breaker=breaker,
    )


# --- ProviderCircuitBreaker aislado -------------------------------------------------


def test_breaker_stays_closed_before_reaching_threshold() -> None:
    breaker = ProviderCircuitBreaker(failure_threshold=3, open_seconds=180)
    breaker.record_failure("gemini")
    breaker.record_failure("gemini")
    assert breaker.is_open("gemini") is False


def test_breaker_opens_after_threshold_failures() -> None:
    breaker = ProviderCircuitBreaker(failure_threshold=3, open_seconds=180)
    for _ in range(3):
        breaker.record_failure("gemini")
    assert breaker.is_open("gemini") is True


def test_breaker_closes_and_resets_after_open_seconds_elapse() -> None:
    from datetime import datetime, timedelta, timezone

    breaker = ProviderCircuitBreaker(failure_threshold=2, open_seconds=60)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    breaker.record_failure("gemini", now=t0)
    breaker.record_failure("gemini", now=t0)
    assert breaker.is_open("gemini", now=t0) is True
    later = t0 + timedelta(seconds=61)
    assert breaker.is_open("gemini", now=later) is False
    # tras cerrarse solo, hace falta volver a fallar 'threshold' veces (el
    # contador se resetea), no basta con un fallo suelto
    breaker.record_failure("gemini", now=later)
    assert breaker.is_open("gemini", now=later) is False


def test_breaker_success_resets_failure_count() -> None:
    breaker = ProviderCircuitBreaker(failure_threshold=3, open_seconds=180)
    breaker.record_failure("gemini")
    breaker.record_failure("gemini")
    breaker.record_success("gemini")
    breaker.record_failure("gemini")
    assert breaker.is_open("gemini") is False  # solo 1 fallo desde el reset


# --- Integracion con ConversationEngine ----------------------------------------------


@pytest.mark.asyncio
async def test_falls_back_to_secondary_provider_when_primary_fails() -> None:
    gemini = _CountingProvider("gemini", fail=True)
    groq = _CountingProvider("groq", fail=False, response="Respondo desde el proveedor de respaldo.")
    eng = _engine(_NamedRegistry({"gemini": gemini, "groq": groq}))
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "hola a todos")

    replies = [m for m in conv.messages if m.sender_id == "gemini"]
    assert len(replies) == 1
    # el mensaje se firma como el ciudadano de siempre (misma personalidad),
    # aunque quien genero el texto haya sido el proveedor de respaldo
    assert replies[0].content == "Respondo desde el proveedor de respaldo."
    assert gemini.calls == 1
    assert groq.calls == 1


@pytest.mark.asyncio
async def test_circuit_opens_after_repeated_failures_and_stops_calling_primary() -> None:
    gemini = _CountingProvider("gemini", fail=True)
    groq = _CountingProvider("groq", fail=False, response="respaldo")
    breaker = ProviderCircuitBreaker(failure_threshold=3, open_seconds=180)
    eng = _engine(_NamedRegistry({"gemini": gemini, "groq": groq}), breaker=breaker)
    conv = eng.ensure_default_conversation("visitor-a")

    for _ in range(4):
        await eng.send_user_message(conv.id, "hola de nuevo")

    # 3 fallos reales abren el circuito; la 4a ronda ya no llama de verdad
    # al proveedor principal, salta directa al de respaldo
    assert gemini.calls == 3
    assert groq.calls == 4
    assert breaker.is_open("gemini") is True


@pytest.mark.asyncio
async def test_no_fallback_configured_keeps_old_unavailable_message() -> None:
    class _LonelyProvider(AIProvider):
        name = "mock_no_fallback"

        def is_configured(self) -> bool:
            return True

        async def chat(self, messages, model, temperature=0.7):
            raise ProviderError("sin cuota")

        async def stream_chat(self, messages, model, temperature=0.7):
            raise ProviderError("sin cuota")
            yield ""  # pragma: no cover

    roster = {
        "solitaria": Participant(
            id="solitaria", name="Solitaria", provider="mock_no_fallback", model="m",
            system_prompt="eres solitaria", avatar="S", color="#fff",
        ),
    }
    eng = ConversationEngine(
        conversations={}, roster=roster, registry=_NamedRegistry({"mock_no_fallback": _LonelyProvider()}),
        event_bus=_FakeBus(), store=_FakeStore(),
    )
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "hola")

    replies = [m for m in conv.messages if m.sender_id == "solitaria"]
    assert len(replies) == 1
    assert "no puede responder ahora mismo" in replies[0].content
