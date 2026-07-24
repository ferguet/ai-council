"""
API del Chat Grupal (Interfaz de conversacion): el centro de la aplicacion.

Todas las IA reales estan presentes por defecto en la sala "General" (sin
que el usuario tenga que anadirlas a mano). El usuario puede crear grupos,
abrir chats privados, mencionar con @Nombre, expulsar temporalmente,
invitar, y mandar mensajes a un subconjunto explicito de IA.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.conversation.attachments import extract_text, kind_for
from app.conversation.engine import ConversationEngine
from app.core.event_bus import Event, event_bus
from app.domain.conversation_models import ConversationKind

router = APIRouter(tags=["conversation"])

# Limite generoso pero prudente: Render free tiene 512MB de RAM y el archivo
# entero pasa por memoria (no hay disco persistente donde volcarlo antes).
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class CreateConversationIn(BaseModel):
    name: str
    participant_ids: list[str] = []
    kind: str = "group"   # "group" | "private"


class KickInviteIn(BaseModel):
    citizen_id: str


def _engine(request: Request) -> ConversationEngine:
    return request.app.state.conversation_engine


@router.get("/conversations/roster")
def get_roster(request: Request) -> list[dict]:
    """IA reales disponibles ahora mismo (con clave configurada). Nada simulado."""
    eng = _engine(request)
    return [
        {"id": p.id, "name": p.name, "avatar": p.avatar, "color": p.color,
         "profession": p.profession, "provider": p.provider}
        for p in eng.roster.values()
    ]


@router.get("/conversations")
def list_conversations(request: Request) -> list[dict]:
    return _engine(request).list_summaries()


@router.post("/conversations")
def create_conversation(body: CreateConversationIn, request: Request) -> dict:
    eng = _engine(request)
    try:
        kind = ConversationKind(body.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="kind debe ser 'group' o 'private'")
    valid_ids = [pid for pid in body.participant_ids if pid in eng.roster]
    if kind == ConversationKind.PRIVATE and len(valid_ids) != 1:
        raise HTTPException(status_code=400, detail="una conversacion privada necesita exactamente 1 IA real valida")
    if not valid_ids:
        raise HTTPException(status_code=400, detail="elige al menos una IA real disponible para el grupo")
    conv = eng.create_conversation(body.name, valid_ids, kind)
    return eng.snapshot(conv.id)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict:
    eng = _engine(request)
    try:
        return eng.snapshot(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/conversations/{conversation_id}/kick")
async def kick(conversation_id: str, body: KickInviteIn, request: Request) -> dict:
    eng = _engine(request)
    try:
        await eng.kick(conversation_id, body.citizen_id)
        return eng.snapshot(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/conversations/{conversation_id}/invite")
async def invite(conversation_id: str, body: KickInviteIn, request: Request) -> dict:
    eng = _engine(request)
    try:
        await eng.invite(conversation_id, body.citizen_id)
        return eng.snapshot(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/conversations/{conversation_id}/attachments")
async def upload_attachment(
    conversation_id: str,
    request: Request,
    file: UploadFile = File(...),
    caption: str = Form(""),
    to: str = Form(""),  # JSON de lista de ids, opcional
) -> dict:
    """Sube un archivo a la sala: se extrae su texto (si el tipo lo permite)
    y se comparte como un mensaje mas, disparando la ronda de respuestas de
    las IA objetivo igual que un mensaje de texto normal."""
    eng = _engine(request)
    if eng.get(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (limite 8 MB)")

    filename = file.filename or "archivo"
    to_ids = None
    if to:
        try:
            parsed = json.loads(to)
            to_ids = parsed if isinstance(parsed, list) and parsed else None
        except json.JSONDecodeError:
            to_ids = None

    extracted = extract_text(filename, content)
    await eng.send_attachment(
        conversation_id, filename=filename, size_bytes=len(content), kind=kind_for(filename),
        extracted_text=extracted, caption=caption, to=to_ids,
    )
    return eng.snapshot(conversation_id)


@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_socket(conversation_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    eng: ConversationEngine = websocket.app.state.conversation_engine

    if eng.get(conversation_id) is None:
        await websocket.send_json({"type": "error", "payload": {"message": "Conversacion no encontrada"}})
        await websocket.close()
        return

    await websocket.send_json({"type": "conversation_state", "payload": eng.snapshot(conversation_id)})

    async def forward(event: Event) -> None:
        try:
            await websocket.send_json({"type": event.type, "payload": event.payload})
        except Exception:
            pass  # el socket puede haberse cerrado; el bucle principal lo detecta

    event_bus.subscribe(conversation_id, forward)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if msg_type == "message":
                content = data.get("content", "")
                to = data.get("to") or None
                await eng.send_user_message(conversation_id, content, to=to)
            elif msg_type == "kick":
                await eng.kick(conversation_id, data.get("citizen_id", ""))
                await websocket.send_json({"type": "conversation_state", "payload": eng.snapshot(conversation_id)})
            elif msg_type == "invite":
                try:
                    await eng.invite(conversation_id, data.get("citizen_id", ""))
                except KeyError as exc:
                    await websocket.send_json({"type": "error", "payload": {"message": str(exc)}})
                await websocket.send_json({"type": "conversation_state", "payload": eng.snapshot(conversation_id)})
            elif msg_type == "get_state":
                await websocket.send_json({"type": "conversation_state", "payload": eng.snapshot(conversation_id)})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(conversation_id, forward)
