"""
Event Bus interno muy simple (pub/sub en memoria, async).

Los modulos no se llaman entre si directamente para notificar cosas como
"un agente ha empezado a responder" o "el debate ha terminado": publican un
evento aqui, y quien este interesado (por ejemplo el endpoint de WebSocket)
se suscribe. Esto mantiene el Orchestrator desacoplado de como se transmiten
los eventos al cliente (podria ser WebSocket hoy y colas/SSE manana).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from collections import defaultdict


@dataclass
class Event:
    type: str
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    """Bus por sesion de debate: cada session_id tiene sus propios suscriptores."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)

    def subscribe(self, session_id: str, callback: Subscriber) -> None:
        self._subscribers[session_id].append(callback)

    def unsubscribe(self, session_id: str, callback: Subscriber) -> None:
        if callback in self._subscribers.get(session_id, []):
            self._subscribers[session_id].remove(callback)

    async def publish(self, event: Event) -> None:
        callbacks = list(self._subscribers.get(event.session_id, []))
        if not callbacks:
            return
        await asyncio.gather(*(cb(event) for cb in callbacks), return_exceptions=True)


# Instancia unica compartida por el proceso (suficiente para el MVP;
# en Fase 2, cuando haya varios workers, esto se sustituye por Redis pub/sub
# sin tocar el resto del codigo, porque todos usan esta interfaz).
event_bus = EventBus()
