"""
"Razonamiento visible": los eventos emergentes (friccion/afinidad social,
invitar a colaborar en un proyecto) llevan un campo `reasoning` opcional que
explica el por que con los datos que el motor ya calcula (confianza,
rivalidad), sin gastar ninguna llamada de IA extra. Estos tests fuerzan las
tiradas de random.random()/random.sample()/random.choice() para que el
resultado sea determinista y comprobable.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core.event_bus import EventBus
from app.domain.city_enums import ActivityType
from app.domain.city_models import CityEvent, EventType
from app.providers.base import AIProvider
from app.providers.mock_provider import MockProvider
from app.simulation import engine as engine_module
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import WorldStore, world_from_dict, world_to_dict
from app.simulation.world_data import build_default_world


class _AllMockRegistry:
    def __init__(self) -> None:
        self._mock = MockProvider()

    def get(self, name: str) -> AIProvider:
        return self._mock


def _engine(world) -> SimulationEngine:
    tmp = tempfile.TemporaryDirectory()
    store = WorldStore(str(Path(tmp.name) / "city_state.json"))
    return SimulationEngine(
        world=world, registry=_AllMockRegistry(), event_bus=EventBus(), store=store,
        hours_per_tick=1, real_ai_interval_minutes=1440,
    )


def _queue(monkeypatch, values: list[float]) -> None:
    """Sustituye random.random() por una cola de valores fijos, en orden."""
    it = iter(values)
    monkeypatch.setattr(engine_module.random, "random", lambda: next(it))


def test_city_event_create_stores_reasoning():
    event = CityEvent.create(EventType.RELACION, sim_day=1, sim_hour=8, description="algo",
                              reasoning="porque si")
    assert event.reasoning == "porque si"


def test_city_event_reasoning_defaults_to_none():
    event = CityEvent.create(EventType.LLEGADA, sim_day=1, sim_hour=8, description="algo")
    assert event.reasoning is None


def test_reasoning_survives_persistence_roundtrip():
    world = build_default_world()
    event = CityEvent.create(EventType.RELACION, world.sim_day, world.sim_hour, "algo",
                              reasoning="confianza alta de antes")
    world.add_event(event)
    reloaded = world_from_dict(world_to_dict(world))
    assert reloaded.events[-1].reasoning == "confianza alta de antes"


@pytest.mark.asyncio
async def test_social_friction_event_explains_prior_rivalry(monkeypatch):
    world = build_default_world()
    ids = list(world.citizens.keys())[:2]
    a, b = (world.citizens[i] for i in ids)
    a.current_activity = ActivityType.SOCIALIZAR
    b.current_activity = ActivityType.SOCIALIZAR
    a.current_building_id = b.current_building_id = "plaza"
    a.relationship_with(b.id).rivalry = 0.6  # rivalidad previa alta
    a.relationship_with(b.id).trust = 0.4

    monkeypatch.setattr(engine_module.random, "sample", lambda seq, k: list(seq))
    monkeypatch.setattr(engine_module.random, "choice", lambda seq: seq[0])
    # 1a llamada: pasa la puerta de _SOCIAL_REINFORCE_CHANCE; 2a: dispara friccion.
    _queue(monkeypatch, [0.0, 0.0])

    eng = _engine(world)
    await eng._maybe_social_events()

    relacion_events = [e for e in world.events if e.type == EventType.RELACION]
    assert len(relacion_events) == 1
    assert relacion_events[0].reasoning is not None
    assert "rivalidad previa" in relacion_events[0].reasoning


@pytest.mark.asyncio
async def test_social_reinforce_event_explains_prior_trust(monkeypatch):
    world = build_default_world()
    ids = list(world.citizens.keys())[:2]
    a, b = (world.citizens[i] for i in ids)
    a.current_activity = ActivityType.SOCIALIZAR
    b.current_activity = ActivityType.SOCIALIZAR
    a.current_building_id = b.current_building_id = "plaza"
    a.relationship_with(b.id).rivalry = 0.0
    a.relationship_with(b.id).trust = 0.8  # ya se fiaban de antes

    monkeypatch.setattr(engine_module.random, "sample", lambda seq, k: list(seq))
    monkeypatch.setattr(engine_module.random, "choice", lambda seq: seq[0])
    # 1a llamada: pasa la puerta; 2a: por debajo de friction_chance -> refuerzo.
    _queue(monkeypatch, [0.0, 0.99])

    eng = _engine(world)
    await eng._maybe_social_events()

    relacion_events = [e for e in world.events if e.type == EventType.RELACION]
    assert len(relacion_events) == 1
    assert relacion_events[0].reasoning is not None
    assert "confianza de antes" in relacion_events[0].reasoning


@pytest.mark.asyncio
async def test_project_invite_reasoning_mentions_trust(monkeypatch):
    world = build_default_world()
    ids = list(world.citizens.keys())
    citizen = world.citizens[ids[0]]
    partner = world.citizens[ids[1]]
    citizen.current_activity = ActivityType.INVESTIGAR
    citizen.relationship_with(partner.id).trust = 0.9
    citizen.current_project_id = None
    partner.current_project_id = None

    monkeypatch.setattr(engine_module.random, "random", lambda: 0.0)  # dispara inicio + invitacion siempre
    monkeypatch.setattr(engine_module, "pick_project_idea", lambda c: ("Proyecto", "Descripcion"))

    eng = _engine(world)
    await eng._maybe_project_work(citizen)

    proyecto_events = [e for e in world.events if e.type == EventType.PROYECTO_INICIADO]
    assert len(proyecto_events) == 1
    assert proyecto_events[0].reasoning is not None
    assert "confía en" in proyecto_events[0].reasoning
