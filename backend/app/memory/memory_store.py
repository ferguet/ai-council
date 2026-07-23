"""
Almacen de sesiones de debate. En este MVP vive en memoria de proceso
(un diccionario). La interfaz esta pensada para que en Fase 2 se sustituya
por Redis (sesiones activas) + Postgres (historico) sin que el Orchestrator
ni la API tengan que cambiar una sola linea: solo se inyectaria otra
implementacion de SessionStore.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import DebateSession


class SessionStore(ABC):
    @abstractmethod
    def save(self, session: DebateSession) -> None: ...

    @abstractmethod
    def get(self, session_id: str) -> DebateSession | None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, DebateSession] = {}

    def save(self, session: DebateSession) -> None:
        self._sessions[session.id] = session

    def get(self, session_id: str) -> DebateSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# Instancia unica del proceso (suficiente para un solo worker; en Fase 2
# se sustituye por RedisSessionStore implementando la misma interfaz).
session_store = InMemorySessionStore()
