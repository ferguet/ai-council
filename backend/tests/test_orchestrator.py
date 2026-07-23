"""
Test del flujo completo del orquestador usando el proveedor Mock, para que
no dependa de red ni de API keys. Verifica lo esencial: el debate arranca,
varios agentes intervienen, y termina (no se queda en bucle infinito).
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.event_bus import EventBus
from app.domain.enums import DebateStatus
from app.domain.models import Agent, DebateSession
from app.orchestrator.director import Director
from app.orchestrator.orchestrator import Orchestrator
from app.providers.registry import ProviderRegistry


@pytest.mark.asyncio
async def test_debate_runs_and_ends_with_mock_provider():
    settings = Settings(director_provider="mock", director_model="director-v1", max_debate_turns=6)
    registry = ProviderRegistry(settings)
    bus = EventBus()
    director = Director(registry.get("mock"), settings.director_model)
    orchestrator = Orchestrator(registry, bus, director, max_turns=settings.max_debate_turns)

    participants = [
        Agent.create("Agente A", "mock", "mock-v1", role="Economista"),
        Agent.create("Agente B", "mock", "mock-v1", role="Ingeniero"),
        Agent.create("Agente C", "mock", "mock-v1", role="Investigador"),
    ]
    session = DebateSession.create(topic="¿Deberíamos lanzar el producto ya?", participants=participants)

    events: list[str] = []

    async def collect(event):
        events.append(event.type)

    bus.subscribe(session.id, collect)

    await orchestrator.run_until_pause_or_end(session)

    assert session.turn_count > 0, "el debate deberia haber ejecutado al menos un turno"
    assert session.status in (
        DebateStatus.ENDED, DebateStatus.CONSENSUS_REACHED, DebateStatus.DEADLOCKED,
    ), "el debate deberia haber terminado, no quedarse activo indefinidamente"
    assert session.turn_count <= settings.max_debate_turns
    assert any(m.sender_id != "director" for m in session.messages), "algun agente deberia haber hablado"
    assert "agent_message_complete" in events or "debate_ended" in events


@pytest.mark.asyncio
async def test_user_can_intervene_mid_debate():
    settings = Settings(director_provider="mock", max_debate_turns=4)
    registry = ProviderRegistry(settings)
    bus = EventBus()
    director = Director(registry.get("mock"), settings.director_model)
    orchestrator = Orchestrator(registry, bus, director, max_turns=settings.max_debate_turns)

    participants = [Agent.create("Agente A", "mock", "mock-v1")]
    session = DebateSession.create(topic="Tema de prueba", participants=participants)

    await orchestrator.add_user_message(session, "Centraos en los riesgos, por favor.")

    assert len(session.messages) == 1
    assert session.messages[0].sender_id == "user"
    assert session.messages[0].content == "Centraos en los riesgos, por favor."
