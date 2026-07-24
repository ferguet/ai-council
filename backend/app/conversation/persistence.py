"""
Persistencia del estado de las conversaciones (JSON local).

Mismo patron que app/simulation/persistence.py: metodos async aunque el
trabajo de fichero sea sincrono, para que esta clase sea intercambiable con
PostgresConversationStore (persistence_pg.py) sin que el resto del codigo
tenga que saber cual de las dos esta usando.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.domain.conversation_models import Attachment, Conversation, ConversationKind, ConversationMessage


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _str_to_dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def conversations_to_dict(conversations: dict[str, Conversation]) -> dict:
    return {
        "conversations": {
            cid: {
                "id": c.id, "name": c.name, "kind": c.kind.value,
                "participant_ids": c.participant_ids, "excluded_ids": c.excluded_ids,
                "owner_visitor_id": c.owner_visitor_id,
                "messages": [
                    {
                        "id": m.id, "sender_id": m.sender_id, "sender_name": m.sender_name,
                        "content": m.content, "mentions": m.mentions, "to": m.to,
                        "attachment": (
                            {
                                "filename": m.attachment.filename, "size_bytes": m.attachment.size_bytes,
                                "kind": m.attachment.kind, "extracted_text": m.attachment.extracted_text,
                                "image_base64": m.attachment.image_base64, "image_mime": m.attachment.image_mime,
                            } if m.attachment else None
                        ),
                        "created_at": _dt_to_str(m.created_at),
                    }
                    for m in c.messages
                ],
                "created_at": _dt_to_str(c.created_at),
            }
            for cid, c in conversations.items()
        }
    }


def conversations_from_dict(data: dict) -> dict[str, Conversation]:
    result: dict[str, Conversation] = {}
    for cid, c in data.get("conversations", {}).items():
        messages = [
            ConversationMessage(
                id=m["id"], sender_id=m["sender_id"], sender_name=m["sender_name"],
                content=m["content"], mentions=m.get("mentions", []), to=m.get("to", []),
                attachment=(
                    Attachment(
                        filename=m["attachment"]["filename"], size_bytes=m["attachment"]["size_bytes"],
                        kind=m["attachment"]["kind"], extracted_text=m["attachment"].get("extracted_text"),
                        image_base64=m["attachment"].get("image_base64"),
                        image_mime=m["attachment"].get("image_mime"),
                    ) if m.get("attachment") else None
                ),
                created_at=_str_to_dt(m.get("created_at")) or datetime.now(timezone.utc),
            )
            for m in c.get("messages", [])
        ]
        result[cid] = Conversation(
            id=c["id"], name=c["name"], kind=ConversationKind(c.get("kind", "group")),
            participant_ids=c.get("participant_ids", []), excluded_ids=c.get("excluded_ids", []),
            # .get(): compatible con salas guardadas antes de que existiera
            # la puerta de acceso, que no tenian dueno.
            owner_visitor_id=c.get("owner_visitor_id"),
            messages=messages, created_at=_str_to_dt(c.get("created_at")) or datetime.now(timezone.utc),
        )
    return result


class ConversationStore:
    """Guarda todas las conversaciones en un unico fichero JSON local."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def exists(self) -> bool:
        return self._path.exists()

    async def load(self) -> dict[str, Conversation]:
        with open(self._path, "r", encoding="utf-8") as f:
            return conversations_from_dict(json.load(f))

    async def save(self, conversations: dict[str, Conversation]) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(conversations_to_dict(conversations), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)

    async def close(self) -> None:
        pass
