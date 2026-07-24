"""Punto de entrada de la aplicacion FastAPI."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents.presets import ROLE_PRESETS
from app.api.city import router as city_router
from app.api.conversation import router as conversation_router
from app.api.websocket import router as websocket_router
from app.conversation.engine import ConversationEngine
from app.conversation.persistence import ConversationStore
from app.conversation.roster import build_active_roster
from app.core.access import check_code, gate_enabled, issue_token, new_visitor_id, require_visitor
from app.core.config import get_settings
from app.core.event_bus import event_bus
from app.providers.registry import ProviderRegistry
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import WorldStore
from app.simulation.scheduler import SimulationScheduler
from app.simulation.world_data import build_default_buildings, build_default_citizens, build_default_world

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
app.include_router(conversation_router)


def _refresh_personalities(world) -> None:
    """Re-aplica personalidad, proveedor y modelo del roster de codigo sobre
    el mundo ya guardado. Sin esto, esos campos quedan congelados en la base
    de datos de la primera vez y cambios en world_data.py (p.ej. corregir el
    nombre de un modelo) no tendrian efecto en la ciudad ya desplegada. Solo
    toca esos 3 campos; NO borra memoria, proyectos, relaciones ni el reloj
    de la ciudad."""
    defaults = build_default_citizens()
    for cid, default in defaults.items():
        citizen = world.citizens.get(cid)
        if citizen is not None:
            citizen.system_prompt = default.system_prompt
            citizen.provider = default.provider
            citizen.model = default.model


def _prune_removed_roster(world) -> None:
    """Quita del mundo ya guardado los ciudadanos y edificios que ya no
    estan en el roster de codigo (p.ej. ciudadanos simulados que se
    decidio eliminar para dejar solo IA reales). Tambien limpia proyectos
    sin ningun propietario vivo y referencias colgantes (edificio actual,
    proyecto actual, relaciones) en los ciudadanos que quedan. Los eventos
    historicos NO se tocan: son un registro, y el frontend ya sabe pintar
    un evento aunque el ciudadano ya no exista."""
    defaults_citizens = build_default_citizens()
    defaults_buildings = build_default_buildings()

    for cid in [c for c in world.citizens if c not in defaults_citizens]:
        del world.citizens[cid]
    for bid in [b for b in world.buildings if b not in defaults_buildings]:
        del world.buildings[bid]

    for pid in [p for p, proj in world.projects.items()
                if not any(oid in world.citizens for oid in proj.owner_ids)]:
        del world.projects[pid]

    for citizen in world.citizens.values():
        if citizen.current_building_id not in world.buildings:
            citizen.current_building_id = (
                citizen.home_id if citizen.home_id in world.buildings
                else next(iter(world.buildings), "")
            )
        if citizen.current_project_id and citizen.current_project_id not in world.projects:
            citizen.current_project_id = None
        citizen.relationships = {
            oid: rel for oid, rel in citizen.relationships.items() if oid in world.citizens
        }


def _sync_new_roster(world) -> None:
    """Anade al mundo ya guardado los edificios y ciudadanos que existen en
    el roster de codigo (world_data.py) pero que todavia no estan en la
    partida persistida (p.ej. porque se anadieron despues del primer
    despliegue). No toca ni reinicia nada de lo que ya existe: solo rellena
    lo que falta, para que ampliar la ciudad en el codigo se refleje en la
    ciudad ya viva sin perder memoria, proyectos ni relaciones."""
    for bid, building in build_default_buildings().items():
        if bid not in world.buildings:
            world.buildings[bid] = building

    defaults = build_default_citizens()
    for cid, citizen in defaults.items():
        if cid in world.citizens:
            continue
        block = citizen.schedule_for_hour(world.sim_hour)
        if block:
            citizen.current_building_id = block.building_id
            citizen.current_activity = block.activity
            citizen.current_activity_label = block.label
        else:
            citizen.current_building_id = citizen.home_id
        world.citizens[cid] = citizen


def _build_store():
    """Postgres si hay DATABASE_URL configurada (necesario para desplegar en
    un servicio gratuito con disco no persistente, p.ej. Render free +
    Supabase); si no, fichero JSON local (vale para correr en tu propio
    PC)."""
    if settings.database_url:
        from app.simulation.persistence_pg import PostgresWorldStore
        return PostgresWorldStore(settings.database_url)
    return WorldStore(settings.sim_data_path)


def _build_conversation_store():
    """Igual que _build_store() pero para el Chat Grupal: Postgres si hay
    DATABASE_URL, si no un JSON local aparte (fichero y tabla distintos a
    los de la Ciudad, misma logica de intercambiabilidad)."""
    if settings.database_url:
        from app.conversation.persistence_pg import PostgresConversationStore
        return PostgresConversationStore(settings.database_url)
    return ConversationStore(settings.conversation_data_path)


@app.on_event("startup")
async def start_city() -> None:
    """Arranca la Ciudad Virtual: carga el mundo guardado (o crea uno nuevo
    la primera vez) y pone el motor de simulacion a correr en segundo
    plano, exista o no alguien conectado viendola."""
    registry = ProviderRegistry(settings)
    store = _build_store()
    world = await store.load() if await store.exists() else build_default_world()
    _prune_removed_roster(world)
    _sync_new_roster(world)
    _refresh_personalities(world)
    await store.save(world)

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

    # Chat Grupal: la sala "General" nace con todas las IA reales ya dentro,
    # sin que el usuario tenga que anadirlas a mano. Reusa el mismo registry
    # de proveedores que la Ciudad (misma configuracion, sin duplicar claves).
    conv_store = _build_conversation_store()
    conversations = await conv_store.load() if await conv_store.exists() else {}
    roster = build_active_roster(registry)
    conv_engine = ConversationEngine(
        conversations=conversations,
        roster=roster,
        registry=registry,
        event_bus=event_bus,
        store=conv_store,
        world=world,
    )
    # La sala 'General' ya no se crea aqui: ahora es por visitante (ver
    # app/core/access.py) y se crea sola la primera vez que cada uno entra
    # (GET /conversations, mas abajo en api/conversation.py).
    app.state.conversation_engine = conv_engine


@app.on_event("shutdown")
async def stop_city() -> None:
    scheduler: SimulationScheduler | None = getattr(app.state, "city_scheduler", None)
    engine: SimulationEngine | None = getattr(app.state, "city_engine", None)
    if scheduler:
        scheduler.stop()
    if engine:
        await engine.save()
        await engine.close()

    conv_engine: ConversationEngine | None = getattr(app.state, "conversation_engine", None)
    if conv_engine:
        await conv_engine.save()
        await conv_engine.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


class VerifyIn(BaseModel):
    code: str


@app.get("/access/status")
def access_status() -> dict:
    """El frontend lo consulta al arrancar: si la puerta no esta activada
    (no hay ACCESS_CODE configurada, p.ej. en local) se salta la pantalla
    de clave por completo."""
    return {"gate_enabled": gate_enabled()}


@app.post("/access/verify")
def access_verify(body: VerifyIn) -> dict:
    """Se llama una vez, la primera vez que alguien abre la app. Si la
    clave es correcta se le da un token propio (ver app/core/access.py):
    a partir de ahi ese token es lo que separa su conversacion de la de
    los demas, sin que haga falta ningun sistema de cuentas."""
    if not check_code(body.code):
        raise HTTPException(status_code=401, detail="Clave incorrecta")
    visitor_id = new_visitor_id()
    return {"token": issue_token(visitor_id), "visitor_id": visitor_id}


@app.get("/providers")
def list_providers(visitor: str = Depends(require_visitor)) -> list[dict]:
    """Que proveedores existen y cuales estan configurados (tienen key/local listo)."""
    registry = ProviderRegistry(get_settings())
    return registry.available()


@app.get("/roles")
def list_roles(visitor: str = Depends(require_visitor)) -> list[dict]:
    return [{"name": name, "color": data["color"]} for name, data in ROLE_PRESETS.items()]


# Sirve el frontend (index.html, city.html) desde el mismo servicio, para
# que en un despliegue en la nube solo haga falta una URL: front y back
# juntos, sin lios de CORS ni de configurar el host del WebSocket a mano.
# Se monta el ultimo a proposito: las rutas de arriba (API) tienen prioridad.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
