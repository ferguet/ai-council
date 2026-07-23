"""Esquemas de entrada/salida de la API (Pydantic). Separados del dominio
a proposito: el dominio no sabe que existe HTTP/WebSocket ni JSON."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ParticipantIn(BaseModel):
    name: str
    provider: str = "mock"
    model: str = "mock-v1"
    role: str = "Generalista"
    system_prompt: str | None = None
    color: str | None = None


class StartDebateIn(BaseModel):
    topic: str = Field(min_length=3)
    participants: list[ParticipantIn]


class UserMessageIn(BaseModel):
    type: str = "user_message"
    content: str
