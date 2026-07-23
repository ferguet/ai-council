"""Punto de entrada de la aplicacion FastAPI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agents.presets import ROLE_PRESETS
from app.api.city import router as city_router
from app.api.websocket import router as websocket_router
from app.core.config import get_settings
from app.core.event_bus import event_bus
from app.providers.registry import ProviderRegistry
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import WorldStore
from app.simulation.scheduler import SimulationScheduler
from app.simulation.world_data import build_default_world

app = FastAPI(
    title="AI Council API",
    description="Backend: varios modelos de IA debaten en /ws/debate, y viven de forma "
                 "persistente como ciudadanos de una Ciudad Virtual en /ws/city.",
    version="0.2.0",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(websocket_router)
app.include_router(city_router)


def _build_store():
    """Postgres si hay DATABASE_URL configurada (necesario para desplegar en
    un servicio gratuito con disco no persistente, p.ej. Render free +
    Supabase); si no, fichero JSON local (vale para correr en tu propio
    PC)."""
    if settings.database_url:
        from app.simulation.persistence_pg import PostgresWorldStore
        return PostgresWorldStore(settings.database_url)
    return WorldStore(settings.sim_data_path)


@app.on_event("startup")
async def start_city() -> None:
    """Arranca la Ciudad Virtual: carga el mundo guardado (o crea uno nuevo
    la primera vez) y pone el motor de simulacion a correr en segundo
    plano, exista o no alguien conectado viendola."""
    registry = ProviderRegistry(settings)
    store = _build_store()
    world = await store.load() if await store.exists() else build_default_world()

    engine = SimulationEngine(
        world=world,
        registry=registry,
        event_bus=event_bus,
        store=store,
        hours_per_tick=settings.sim_hours_per_tick,
        real_ai_interval_minutes=settings.sim_real_ai_interval_minutes,
    )
    scheduler = SimulationScheduler(engine, tick_seconds=settings.sim_tick_seconds)

    app.state.city_engine = engine
    app.state.city_scheduler = scheduler
    if settings.sim_autostart:
        scheduler.start()


@app.on_event("shutdown")
async def stop_city() -> None:
    scheduler: SimulationScheduler | None = getattr(app.state, "city_scheduler", None)
    engine: SimulationEngine | None = getattr(app.state, "city_engine", None)
    if scheduler:
        scheduler.stop()
    if engine:
        await engine.save()
        await engine.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/providers")
def list_providers() -> list[dict]:
    """Que proveedores existen y cuales estan configurados (tienen key/local listo)."""
    registry = ProviderRegistry(get_settings())
    return registry.available()


@app.get("/roles")
def list_roles() -> list[dict]:
    return [{"name": name, "color": data["color"]} for name, data in ROLE_PRESETS.items()]


# Sirve el frontend (index.html, city.html) desde el mismo servicio, para
# que en un despliegue en la nube solo haga falta una URL: front y back
# juntos, sin lios de CORS ni de configurar el host del WebSocket a mano.
# Se monta el ultimo a proposito: las rutas de arriba (API) tienen prioridad.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
