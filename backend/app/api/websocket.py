"""
Endpoint de WebSocket: un cliente se conecta, manda la config inicial del
debate (tema + participantes), el servidor crea la sesion y arranca el
Orchestrator. Cada evento del debate (typing, chunk de texto, mensaje
completo, decision del Director, fin del debate) se reenvia al cliente
como JSON en tiempo real. El cliente puede mandar mensajes de usuario en
cualquier momento para intervenir.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.presets import ROLE_PRESETS
from app.api.schemas import StartDebateIn
from app.core.config import get_settings
from app.core.event_bus import Event, event_bus
from app.domain.enums import DebateStatus
from app.domain.models import Agent, DebateSession
from app.memory.memory_store import session_store
from app.orchestrator.director import Director
from app.orchestrator.orchestrator import Orchestrator
from app.providers.registry import ProviderRegistry

router = APIRouter()


def _build_agent(p, index: int) -> Agent:
    preset = ROLE_PRESETS.get(p.role, ROLE_PRESETS["Generalista"])
    return Agent.create(
        name=p.name,
        provider=p.provider,
        model=p.model,
        role=p.role,
        system_prompt=p.system_prompt or preset["system_prompt"],
        color=p.color or preset["color"],
    )


@router.websocket("/ws/debate")
async def debate_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    registry = ProviderRegistry(settings)

    try:
        init_raw = await websocket.receive_text()
        init = StartDebateIn.model_validate(json.loads(init_raw))
    except Exception as exc:
        await websocket.send_json({"type": "error", "payload": {"message": f"Configuracion invalida: {exc}"}})
        await websocket.close()
        return

    participants = [_build_agent(p, i) for i, p in enumerate(init.participants)]
    session = DebateSession.create(topic=init.topic, participants=participants)
    session_store.save(session)

    director_provider = registry.get(settings.director_provider)
    director = Director(director_provider, settings.director_model)
    orchestrator = Orchestrator(registry, event_bus, director, max_turns=settings.max_debate_turns)

    async def forward(event: Event) -> None:
        try:
            await websocket.send_json({"type": event.type, "payload": event.payload})
        except Exception:
            pass  # el socket puede haberse cerrado; el bucle principal lo detecta

    event_bus.subscribe(session.id, forward)
    await websocket.send_json({
        "type": "session_started",
        "payload": {
            "session_id": session.id,
            "participants": [
                {"id": a.id, "name": a.name, "role": a.role, "color": a.color} for a in participants
            ],
        },
    })

    debate_task = asyncio.create_task(orchestrator.run_until_pause_or_end(session))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "user_message":
                await orchestrator.add_user_message(session, data.get("content", ""))
                if debate_task.done() and session.status != DebateStatus.ACTIVE:
                    session.status = DebateStatus.ACTIVE
                    debate_task = asyncio.create_task(orchestrator.run_until_pause_or_end(session))
            elif data.get("type") == "pause":
                session.status = DebateStatus.PAUSED
            elif data.get("type") == "resume":
                if session.status != DebateStatus.ACTIVE:
                    session.status = DebateStatus.ACTIVE
                    debate_task = asyncio.create_task(orchestrator.run_until_pause_or_end(session))
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(session.id, forward)
        if not debate_task.done():
            debate_task.cancel()
