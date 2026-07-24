"""
API de la Ciudad Virtual: snapshot del mundo, eventos, proyectos, y un
WebSocket para recibir en vivo lo que va ocurriendo (movimientos,
pensamientos, proyectos) y para hablar directamente con un ciudadano.

A diferencia de /ws/debate, aqui no se crea nada al conectar: la ciudad ya
existe (la mantiene viva el SimulationScheduler en segundo plano) y el
cliente simplemente se asoma a verla.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.core.access import require_visitor, require_visitor_ws
from app.core.event_bus import Event, event_bus
from app.providers.base import ChatMessage
from app.simulation.engine import CITY_SESSION_ID, SimulationEngine
from app.simulation.persistence import world_to_dict

router = APIRouter(tags=["city"])


def _engine(request: Request) -> SimulationEngine:
    return request.app.state.city_engine


@router.get("/city/state")
def get_state(request: Request, visitor: str = Depends(require_visitor)) -> dict:
    return _engine(request).snapshot()


@router.get("/city/citizens/{citizen_id}")
def get_citizen(citizen_id: str, request: Request, visitor: str = Depends(require_visitor)) -> dict:
    data = world_to_dict(_engine(request).world)
    citizen = data["citizens"].get(citizen_id)
    if citizen is None:
        raise HTTPException(status_code=404, detail="Ciudadano no encontrado")
    return citizen


@router.get("/city/events")
def get_events(request: Request, limit: int = 50, visitor: str = Depends(require_visitor)) -> list[dict]:
    return _engine(request).recent_events(limit)


@router.get("/city/projects")
def get_projects(request: Request, visitor: str = Depends(require_visitor)) -> list[dict]:
    data = world_to_dict(_engine(request).world)
    return list(data["projects"].values())


@router.get("/city/news")
def get_news(request: Request, limit: int = 20, visitor: str = Depends(require_visitor)) -> list[dict]:
    """Ediciones del periodico de la ciudad, mas reciente primero."""
    return _engine(request).recent_news(limit)


@router.post("/city/news/generate")
async def generate_news(request: Request, visitor: str = Depends(require_visitor)) -> dict:
    """Fuerza una edicion nueva ahora mismo (salta el intervalo de
    news_interval_hours), para probar o para pedir un resumen a demanda."""
    edition = await _engine(request).generate_news_edition(force=True)
    if edition is None:
        raise HTTPException(
            status_code=503,
            detail="No se pudo generar la edicion (proveedor de noticias no disponible o sin respuesta).",
        )
    return {
        "id": edition.id, "sim_day": edition.sim_day, "headline": edition.headline,
        "body": edition.body, "created_at": edition.created_at.isoformat(),
    }


@router.websocket("/ws/city")
async def city_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    token = websocket.query_params.get("visitor")
    if not require_visitor_ws(token):
        await websocket.send_json({"type": "error", "payload": {"message": "Falta la clave de acceso o no es valida"}})
        await websocket.close(code=4401)
        return
    engine: SimulationEngine = websocket.app.state.city_engine

    await websocket.send_json({"type": "world_state", "payload": engine.snapshot()})

    async def forward(event: Event) -> None:
        try:
            await websocket.send_json({"type": event.type, "payload": event.payload})
        except Exception:
            pass  # el socket puede haberse cerrado; el bucle principal lo detecta

    event_bus.subscribe(CITY_SESSION_ID, forward)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if msg_type == "talk":
                citizen_id = data.get("citizen_id", "")
                content = data.get("content", "")
                history = [
                    ChatMessage(role=h.get("role", "user"), content=h.get("content", ""))
                    for h in data.get("history", [])
                ]
                await websocket.send_json({"type": "talk_typing", "payload": {"citizen_id": citizen_id}})
                try:
                    reply = await engine.talk_to_citizen(citizen_id, content, history)
                    await websocket.send_json({
                        "type": "talk_reply",
                        "payload": {"citizen_id": citizen_id, "content": reply},
                    })
                except KeyError as exc:
                    await websocket.send_json({"type": "error", "payload": {"message": str(exc)}})
            elif msg_type == "get_state":
                await websocket.send_json({"type": "world_state", "payload": engine.snapshot()})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(CITY_SESSION_ID, forward)
