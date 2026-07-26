"""
Pausa por inactividad de la Ciudad Virtual.

Motivacion real: la ciudad corria 24/7 con ~11 ciudadanos pensando con IA
real cada 15 minutos, mirase alguien o no. Eso son ~1000 llamadas al dia que
se comian la cuota gratuita de los proveedores aunque nadie abriese la app.
Ahora, si nadie se asoma, se pausan SOLO las llamadas de pago: el reloj, los
horarios y el humor siguen avanzando porque no cuestan nada.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.event_bus import EventBus
from app.simulation.engine import SimulationEngine
from app.simulation.world_data import build_default_world


class _FakeStore:
    async def save(self, world) -> None:
        pass

    async def close(self) -> None:
        pass


class _UnconfiguredProvider:
    def is_configured(self) -> bool:
        return False


class _FakeRegistry:
    """Cuenta cuantas veces se ha pedido un proveedor, sin llamar a nada real."""

    def __init__(self) -> None:
        self.gets: list[str] = []

    def get(self, name: str):
        self.gets.append(name)
        return _UnconfiguredProvider()


def _engine(idle_pause_minutes: int, registry=None) -> SimulationEngine:
    return SimulationEngine(
        world=build_default_world(),
        registry=registry or _FakeRegistry(),
        event_bus=EventBus(),
        store=_FakeStore(),
        idle_pause_minutes=idle_pause_minutes,
    )


def test_arranca_en_pausa_hasta_que_alguien_mira() -> None:
    eng = _engine(30)
    assert eng.is_idle() is True

    eng.note_viewer()
    assert eng.is_idle() is False


def test_vuelve_a_pausarse_pasado_el_margen() -> None:
    eng = _engine(30)
    eng.note_viewer()
    # simula que la ultima visita fue hace 31 minutos
    eng.last_viewer_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    assert eng.is_idle() is True


def test_no_se_pausa_con_la_ciudad_abierta_en_vivo() -> None:
    """Aunque hayan pasado horas: si el WebSocket sigue abierto, alguien la
    esta mirando y no hay que pausar nada."""
    eng = _engine(30)
    eng.viewer_connected()
    eng.last_viewer_at = datetime.now(timezone.utc) - timedelta(hours=5)
    assert eng.is_idle() is False

    eng.viewer_disconnected()
    eng.last_viewer_at = datetime.now(timezone.utc) - timedelta(hours=5)
    assert eng.is_idle() is True


def test_cero_desactiva_la_pausa() -> None:
    eng = _engine(0)
    assert eng.is_idle() is False  # nunca se pausa, como funcionaba antes


@pytest.mark.asyncio
async def test_en_pausa_no_se_pide_ningun_proveedor() -> None:
    registry = _FakeRegistry()
    eng = _engine(30, registry=registry)
    assert eng.is_idle() is True

    await eng.tick()

    # Solo el periodico (1 llamada cada 24h, a proposito NO se pausa). Ningun
    # ciudadano ha pensado: eso es lo que se lleva la cuota.
    assert registry.gets == ["glm"]
    assert eng.world.tick_count == 1      # el reloj SI ha avanzado


@pytest.mark.asyncio
async def test_al_mirar_vuelven_a_pedirse_proveedores() -> None:
    registry = _FakeRegistry()
    eng = _engine(30, registry=registry)
    eng.note_viewer()
    assert eng.is_idle() is False

    await eng.tick()

    assert registry.gets, "con alguien mirando, los ciudadanos despiertos deben intentar pensar"


@pytest.mark.asyncio
async def test_el_reloj_avanza_aunque_este_en_pausa() -> None:
    eng = _engine(30)
    hora_inicial = eng.world.sim_hour

    await eng.tick()

    assert eng.world.sim_hour != hora_inicial
