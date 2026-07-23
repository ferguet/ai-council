"""
Modelos de dominio puros. No importan nada de providers/api/orchestrator:
representan "que es un debate", no "como se ejecuta" ni "como se transmite".
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import DebateStatus, MessageType


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Agent:
    """Un participante del debate: una IA con proveedor, modelo, rol y personalidad."""

    id: str
    name: str
    provider: str          # "mock" | "gemini" | "groq" | "ollama" | ...
    model: str              # nombre del modelo dentro del proveedor
    role: str = "Generalista"
    system_prompt: str = ""
    color: str = "#6C5CE7"   # para pintarlo en el frontend
    private_memory: list[str] = field(default_factory=list)

    @staticmethod
    def create(name: str, provider: str, model: str, role: str = "Generalista",
               system_prompt: str = "", color: str = "#6C5CE7") -> "Agent":
        return Agent(id=_new_id(), name=name, provider=provider, model=model,
                     role=role, system_prompt=system_prompt, color=color)


@dataclass
class Message:
    id: str
    sender_id: str          # id de Agent, "user", o "director"
    sender_name: str
    content: str
    type: MessageType
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(sender_id: str, sender_name: str, content: str,
               type: MessageType = MessageType.STATEMENT) -> "Message":
        return Message(id=_new_id(), sender_id=sender_id, sender_name=sender_name,
                       content=content, type=type)


@dataclass
class SharedMemoryEntry:
    """Un hecho o decision aceptada por el consejo, visible para todos."""
    id: str
    content: str
    proposed_by: str
    created_at: datetime = field(default_factory=_now)


@dataclass
class DebateSession:
    """Una sesion de debate: el tema, los participantes, el historial y su estado."""

    id: str
    topic: str
    participants: list[Agent]
    messages: list[Message] = field(default_factory=list)
    shared_memory: list[SharedMemoryEntry] = field(default_factory=list)
    status: DebateStatus = DebateStatus.ACTIVE
    turn_count: int = 0
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(topic: str, participants: list[Agent]) -> "DebateSession":
        return DebateSession(id=_new_id(), topic=topic, participants=participants)

    def get_agent(self, agent_id: str) -> Agent | None:
        return next((a for a in self.participants if a.id == agent_id), None)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def add_shared_fact(self, content: str, proposed_by: str) -> None:
        self.shared_memory.append(
            SharedMemoryEntry(id=_new_id(), content=content, proposed_by=proposed_by)
        )

    def recent_transcript(self, limit: int = 30) -> list[Message]:
        return self.messages[-limit:]
