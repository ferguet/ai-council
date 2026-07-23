"""
Test de humo de la Ciudad Virtual: que el motor de simulacion pueda avanzar
muchos ticks seguidos sin romperse, usando solo el proveedor mock (sin
gastar ninguna llamada real), y que la persistencia a disco funcione
(guardar + recargar debe reconstruir el mismo mundo).
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.core.event_bus import EventBus
from app.providers.base import AIProvider
from app.providers.mock_provider import MockProvider
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import WorldStore
from app.simulation.world_data import build_default_world


class _AllMockRegistry:
    """Sustituye a ProviderRegistry en el test: cualquier proveedor pedido
    devuelve MockProvider, para no depender de claves ni tocar la red."""

    def __init__(self) -> None:
        self._mock = MockProvider()

    def get(self, name: str) -> AIProvider:
        return self._mock


@pytest.mark.asyncio
async def test_many_ticks_do_not_crash() -> None:
    world = build_default_world()
    with tempfile.TemporaryDirectory() as tmp:
        store = WorldStore(str(Path(tmp) / "city_state.json"))
        engine = SimulationEngine(
            world=world, registry=_AllMockRegistry(), event_bus=EventBus(),
            store=store, hours_per_tick=1, real_ai_interval_minutes=1440,
        )
        for _ in range(48):  # dos dias completos
            await engine.tick()

    assert world.sim_day >= 2
    assert world.tick_count == 48
    # con 7 ciudadanos moviendose 48 veces, tiene que haber pasado algo
    assert len(world.events) > 0


@pytest.mark.asyncio
async def test_save_and_reload_preserves_state() -> None:
    world = build_default_world()
    with tempfile.TemporaryDirectory() as tmp:
        store = WorldStore(str(Path(tmp) / "city_state.json"))
        engine = SimulationEngine(
            world=world, registry=_AllMockRegistry(), event_bus=EventBus(),
            store=store, hours_per_tick=1, real_ai_interval_minutes=1440,
        )
        for _ in range(10):
            await engine.tick()
        await engine.save()

        reloaded = await store.load()
        assert reloaded.sim_day == world.sim_day
        assert reloaded.sim_hour == world.sim_hour
        assert reloaded.tick_count == world.tick_count
        assert set(reloaded.citizens.keys()) == set(world.citizens.keys())
        assert set(reloaded.buildings.keys()) == set(world.buildings.keys())
        for citizen_id, citizen in world.citizens.items():
            assert reloaded.citizens[citizen_id].current_building_id == citizen.current_building_id


@pytest.mark.asyncio
async def test_talk_to_citizen_returns_text_and_remembers_it() -> None:
    world = build_default_world()
    with tempfile.TemporaryDirectory() as tmp:
        store = WorldStore(str(Path(tmp) / "city_state.json"))
        engine = SimulationEngine(
            world=world, registry=_AllMockRegistry(), event_bus=EventBus(),
            store=store, hours_per_tick=1, real_ai_interval_minutes=1440,
        )
        reply = await engine.talk_to_citizen("claude", "Hola, ¿que investigas hoy?")
        assert isinstance(reply, str) and reply.strip() != ""
        assert any("visitante" in m for m in world.citizens["claude"].memory)


def test_talk_to_unknown_citizen_raises_keyerror() -> None:
    world = build_default_world()
    with tempfile.TemporaryDirectory() as tmp:
        store = WorldStore(str(Path(tmp) / "city_state.json"))
        engine = SimulationEngine(
            world=world, registry=_AllMockRegistry(), event_bus=EventBus(),
            store=store,
        )
        with pytest.raises(KeyError):
            asyncio.get_event_loop().run_until_complete(
                engine.talk_to_citizen("no-existe", "hola")
            )
