"""
Modelos de dominio del Chat Grupal (Interfaz de conversacion): el centro de
la aplicacion. A diferencia del debate (app/domain/models.py, sesiones
efimeras con Director que decide turnos) y de la ciudad (vida de fondo,
24/7, aunque nadie mire), esto es una conversacion en vivo iniciada por el
usuario, con todas las IA reales presentes por defecto.

Reutiliza el roster de la Ciudad Virtual (mismos ciudadanos, misma
personalidad "sin filtros") en vez de duplicar personajes: Participant es
una foto ligera de un Citizen, solo con lo que hace falta para conversar.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class ConversationKind(str, Enum):
    DEFAULT = "default"     # la sala principal, con todas las IA reales
    GROUP = "group"          # grupo creado por el usuario con un subconjunto
    PRIVATE = "private"      # conversacion 1:1 con una sola IA


@dataclass
class Participant:
    """Foto ligera de un ciudadano/IA real, solo lo necesario para chatear."""

    id: str
    name: str
    provider: str
    model: str
    avatar: str
    color: str
    system_prompt: str
    profession: str = ""


@dataclass
class Attachment:
    """Metadatos de un archivo adjunto a un mensaje. El binario no se
    guarda en ningun sitio persistente (Render free no tiene disco fijo):
    solo se conserva el texto ya extraido en el momento de la subida, que
    es lo que las IA acaban leyendo como parte del mensaje."""

    filename: str
    size_bytes: int
    kind: str                      # "pdf" | "word" | "excel" | "zip" | "image" | "video" | "audio" | "code" | "file"
    extracted_text: str | None = None   # None si el tipo no se pudo leer como texto


@dataclass
class ConversationMessage:
    id: str
    sender_id: str              # id de Participant, o "user"
    sender_name: str
    content: str
    mentions: list[str] = field(default_factory=list)   # ids mencionados con @
    to: list[str] = field(default_factory=list)          # subconjunto explicito (si lo hubo)
    attachment: Attachment | None = None
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(sender_id: str, sender_name: str, content: str,
               mentions: list[str] | None = None, to: list[str] | None = None,
               attachment: Attachment | None = None) -> "ConversationMessage":
        return ConversationMessage(
            id=_new_id(), sender_id=sender_id, sender_name=sender_name, content=content,
            mentions=mentions or [], to=to or [], attachment=attachment,
        )


@dataclass
class Conversation:
    """Una sala de chat: quien esta dentro, quien esta expulsado temporalmente,
    y el historial. Persiste igual que la ciudad, para que sobreviva a
    reinicios del servicio."""

    id: str
    name: str
    kind: ConversationKind
    participant_ids: list[str] = field(default_factory=list)   # quienes pertenecen a la sala
    excluded_ids: list[str] = field(default_factory=list)       # expulsados temporalmente (siguen en la sala, pero callados)
    messages: list[ConversationMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(name: str, kind: ConversationKind, participant_ids: list[str]) -> "Conversation":
        return Conversation(id=_new_id(), name=name, kind=kind, participant_ids=list(participant_ids))

    def add_message(self, message: ConversationMessage, cap: int = 400) -> None:
        self.messages.append(message)
        if len(self.messages) > cap:
            self.messages = self.messages[-cap:]

    def active_participant_ids(self) -> list[str]:
        return [pid for pid in self.participant_ids if pid not in self.excluded_ids]

    def recent_messages(self, limit: int = 60) -> list[ConversationMessage]:
        return self.messages[-limit:]
