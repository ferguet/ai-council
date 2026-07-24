"""
Periodico diario de la ciudad: una IA redacta un resumen periodistico de los
hechos reales acumulados (nunca inventados), como mucho una vez cada
news_interval_hours, y siempre que se fuerce a mano (boton "Generar ahora").
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.event_bus import EventBus
from app.domain.city_enums import EventType
from app.domain.city_models import CityEvent
from app.providers.base import AIProvider
from app.providers.mock_provider import MockProvider
from app.simulation.activities import build_newspaper_prompt, parse_newspaper_reply
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import WorldStore, world_from_dict, world_to_dict
from app.simulation.world_data import build_default_world


class _AllMockRegistry:
    def __init__(self) -> None:
        self._mock = MockProvider()

    def get(self, name: str) -> AIProvider:
        return self._mock


def _engine(world, **kwargs) -> tuple[SimulationEngine, WorldStore, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    store = WorldStore(str(Path(tmp.name) / "city_state.json"))
    engine = SimulationEngine(
        world=world, registry=_AllMockRegistry(), event_bus=EventBus(), store=store,
        hours_per_tick=1, real_ai_interval_minutes=1440, **kwargs,
    )
    return engine, store, tmp


def test_parse_newspaper_reply_extracts_headline_and_body():
    text = "TITULAR: La ciudad discute el drenaje\nCUERPO: Varios ciudadanos han debatido hoy sobre el estado del tunel."
    headline, body = parse_newspaper_reply(text, sim_day=3)
    assert headline == "La ciudad discute el drenaje"
    assert "drenaje" not in body  # el cuerpo es el texto de despues, no repite el titular
    assert "tunel" in body


def test_parse_newspaper_reply_falls_back_when_format_missing():
    headline, body = parse_newspaper_reply("un texto libre sin las etiquetas pedidas", sim_day=5)
    assert headline == "Edición del día 5"
    assert body == "un texto libre sin las etiquetas pedidas"


def test_build_newspaper_prompt_includes_event_descriptions():
    world = build_default_world()
    event = CityEvent.create(EventType.SUGERENCIA, world.sim_day, world.sim_hour, "Alguien sugiere algo muy concreto.")
    prompt = build_newspaper_prompt(world, [event])
    system_text = prompt[0].content
    assert "Alguien sugiere algo muy concreto." in system_text
    assert "TITULAR" in system_text and "CUERPO" in system_text


@pytest.mark.asyncio
async def test_generate_news_edition_creates_edition_from_real_events():
    world = build_default_world()
    world.add_event(CityEvent.create(EventType.PROYECTO_INICIADO, world.sim_day, world.sim_hour, "Gemini inicia un proyecto nuevo."))
    engine, _store, tmp = _engine(world)
    try:
        edition = await engine.generate_news_edition()
        assert edition is not None
        assert edition in world.news
        assert world.last_news_at is not None
        assert edition.headline.strip() != ""
        assert edition.body.strip() != ""
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_generate_news_edition_respects_interval_without_force():
    world = build_default_world()
    world.add_event(CityEvent.create(EventType.PROYECTO_INICIADO, world.sim_day, world.sim_hour, "Un evento cualquiera."))
    engine, _store, tmp = _engine(world, news_interval_hours=24)
    try:
        first = await engine.generate_news_edition()
        assert first is not None
        # inmediatamente despues, sin forzar, no toca generar otra
        second = await engine.generate_news_edition()
        assert second is None
        assert len(world.news) == 1
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_generate_news_edition_force_bypasses_interval():
    world = build_default_world()
    world.add_event(CityEvent.create(EventType.PROYECTO_INICIADO, world.sim_day, world.sim_hour, "Un evento cualquiera."))
    engine, _store, tmp = _engine(world, news_interval_hours=24)
    try:
        first = await engine.generate_news_edition()
        assert first is not None
        second = await engine.generate_news_edition(force=True)
        assert second is not None
        assert len(world.news) == 2
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_generate_news_edition_skips_when_no_events_and_not_forced():
    world = build_default_world()  # mundo recien creado, sin eventos
    engine, _store, tmp = _engine(world)
    try:
        edition = await engine.generate_news_edition()
        assert edition is None
        assert world.news == []
    finally:
        tmp.cleanup()


def test_news_survives_persistence_roundtrip():
    world = build_default_world()
    world.add_event(CityEvent.create(EventType.PROYECTO_INICIADO, world.sim_day, world.sim_hour, "Evento de prueba."))
    from app.domain.city_models import NewsEdition
    edition = NewsEdition.create(world.sim_day, "Titular de prueba", "Cuerpo de prueba con varias frases.")
    world.add_news(edition)
    world.last_news_at = datetime.now(timezone.utc) - timedelta(hours=1)

    data = world_to_dict(world)
    reloaded = world_from_dict(data)

    assert len(reloaded.news) == 1
    assert reloaded.news[0].headline == "Titular de prueba"
    assert reloaded.news[0].body == "Cuerpo de prueba con varias frases."
    assert reloaded.last_news_at is not None
