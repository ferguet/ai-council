"""
Motor de simulacion de la Ciudad Virtual.

Este es el corazon de la caracteristica: gobierna la ciudad de forma
independiente del chat. Cada tick() representa que avanza el tiempo
simulado, y con el:

- Los ciudadanos se mueven segun su rutina (schedule).
- Trabajan en proyectos propios (se inician, avanzan, se completan).
- De vez en cuando "piensan en voz alta" con una llamada real a su proveedor
  de IA (limitada por intervalo, para controlar el coste).
- Los que socializan en el mismo edificio pueden reforzar su relacion.

Todo esto ocurre exista o no un cliente conectado por WebSocket: el
scheduler (scheduler.py) llama a tick() en un bucle de fondo mientras el
proceso este vivo.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.core.event_bus import Event, EventBus
from app.domain.city_enums import ActivityType, EventType, ProjectStatus
from app.domain.city_models import Citizen, CityEvent, Project, WorldState
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.simulation.activities import (
    arrival_text,
    build_talk_prompt,
    build_thought_prompt,
    pick_project_idea,
    project_log_entry,
)
from app.simulation.persistence import WorldStore, world_to_dict

CITY_SESSION_ID = "city-world"

# Probabilidades por tick, deliberadamente bajas: la ciudad debe sentirse
# viva pero sin que cada tick sea un aluvion de eventos.
_PROJECT_START_CHANCE = 0.15
_PROJECT_ADVANCE_CHANCE = 0.4
_SOCIAL_REINFORCE_CHANCE = 0.3


class SimulationEngine:
    def __init__(
        self,
        world: WorldState,
        registry: ProviderRegistry,
        event_bus: EventBus,
        store: WorldStore,
        hours_per_tick: int = 1,
        real_ai_interval_minutes: int = 15,
    ) -> None:
        self.world = world
        self._registry = registry
        self._event_bus = event_bus
        self._store = store
        self._hours_per_tick = hours_per_tick
        self._real_ai_interval = timedelta(minutes=real_ai_interval_minutes)

    async def _emit(self, type_: str, payload: dict) -> None:
        await self._event_bus.publish(Event(type=type_, session_id=CITY_SESSION_ID, payload=payload))

    @staticmethod
    def _event_payload(event: CityEvent) -> dict:
        return {
            "id": event.id, "type": event.type.value, "sim_day": event.sim_day,
            "sim_hour": event.sim_hour, "citizen_ids": event.citizen_ids,
            "building_id": event.building_id, "description": event.description,
        }

    def _record_event(self, event: CityEvent) -> None:
        self.world.add_event(event)

    def _advance_time(self) -> None:
        self.world.sim_hour += self._hours_per_tick
        while self.world.sim_hour >= 24:
            self.world.sim_hour -= 24
            self.world.sim_day += 1

    async def tick(self) -> None:
        self.world.tick_count += 1
        self._advance_time()

        for citizen in self.world.citizens.values():
            await self._update_citizen_schedule(citizen)
            await self._maybe_project_work(citizen)
            await self._maybe_real_thought(citizen)

        await self._maybe_social_events()

        await self._store.save(self.world)
        await self._emit("world_tick", {
            "sim_day": self.world.sim_day, "sim_hour": self.world.sim_hour,
            "tick_count": self.world.tick_count,
        })

    async def _update_citizen_schedule(self, citizen: Citizen) -> None:
        block = citizen.schedule_for_hour(self.world.sim_hour)
        if not block:
            return
        moved = citizen.current_building_id != block.building_id
        citizen.current_building_id = block.building_id
        citizen.current_activity = block.activity
        citizen.current_activity_label = block.label
        if not moved:
            return
        building = self.world.buildings.get(block.building_id)
        text = arrival_text(citizen, building) if building else block.label
        event = CityEvent.create(
            EventType.LLEGADA, self.world.sim_day, self.world.sim_hour,
            f"{citizen.name} {text}", citizen_ids=[citizen.id], building_id=block.building_id,
        )
        self._record_event(event)
        await self._emit("city_event", self._event_payload(event))

    async def _maybe_project_work(self, citizen: Citizen) -> None:
        productive = citizen.current_activity in (
            ActivityType.INVESTIGAR, ActivityType.PROGRAMAR,
            ActivityType.GESTIONAR, ActivityType.VOTAR,
        )
        if not productive:
            return

        if not citizen.current_project_id or citizen.current_project_id not in self.world.projects:
            if random.random() >= _PROJECT_START_CHANCE:
                return
            title, description = pick_project_idea(citizen)
            project = Project.create(title, description, [citizen.id], citizen.current_building_id)
            self.world.projects[project.id] = project
            citizen.current_project_id = project.id
            citizen.remember(f"{self.world.sim_time_label()}: inicie el proyecto '{title}'.")
            event = CityEvent.create(
                EventType.PROYECTO_INICIADO, self.world.sim_day, self.world.sim_hour,
                f"{citizen.name} inicia un nuevo proyecto: {title}.",
                citizen_ids=[citizen.id], building_id=citizen.current_building_id,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))
            return

        project = self.world.projects[citizen.current_project_id]
        if project.status != ProjectStatus.ACTIVO:
            citizen.current_project_id = None
            return
        if random.random() >= _PROJECT_ADVANCE_CHANCE:
            return

        amount = random.randint(5, 15)
        log_text = project_log_entry()
        project.advance(amount, f"{citizen.name} {log_text}")
        citizen.remember(f"{self.world.sim_time_label()}: en '{project.title}', {log_text}")

        if project.status == ProjectStatus.COMPLETADO:
            citizen.current_project_id = None
            description = f"{citizen.name} completa el proyecto '{project.title}'."
            event_type = EventType.PROYECTO_COMPLETADO
        else:
            description = f"{citizen.name} avanza en '{project.title}' ({project.progress}%)."
            event_type = EventType.PROYECTO_AVANCE
        event = CityEvent.create(
            event_type, self.world.sim_day, self.world.sim_hour, description,
            citizen_ids=[citizen.id], building_id=citizen.current_building_id,
        )
        self._record_event(event)
        await self._emit("city_event", self._event_payload(event))

    async def _maybe_real_thought(self, citizen: Citizen) -> None:
        if citizen.current_activity == ActivityType.DESCANSAR:
            return  # no gastamos llamadas reales mientras duermen
        provider = self._registry.get(citizen.provider)
        if not provider.is_configured():
            return
        now = datetime.now(timezone.utc)
        if citizen.last_real_ai_call and (now - citizen.last_real_ai_call) < self._real_ai_interval:
            return

        citizen.last_real_ai_call = now  # se marca antes de llamar: evita reintentos en bucle si falla
        try:
            prompt = build_thought_prompt(citizen, self.world)
            text = (await provider.chat(prompt, citizen.model, temperature=0.9)).strip()
        except ProviderError:
            return
        if not text:
            return

        citizen.remember(text)
        event = CityEvent.create(
            EventType.PENSAMIENTO, self.world.sim_day, self.world.sim_hour,
            f"{citizen.name}: “{text}”",
            citizen_ids=[citizen.id], building_id=citizen.current_building_id,
        )
        self._record_event(event)
        await self._emit("city_event", self._event_payload(event))

    async def _maybe_social_events(self) -> None:
        by_building: dict[str, list[Citizen]] = {}
        for citizen in self.world.citizens.values():
            if citizen.current_activity == ActivityType.SOCIALIZAR:
                by_building.setdefault(citizen.current_building_id, []).append(citizen)

        for building_id, group in by_building.items():
            if len(group) < 2 or random.random() >= _SOCIAL_REINFORCE_CHANCE:
                continue
            a, b = random.sample(group, 2)
            a.relationship_with(b.id).reinforce()
            b.relationship_with(a.id).reinforce()
            event = CityEvent.create(
                EventType.RELACION, self.world.sim_day, self.world.sim_hour,
                f"{a.name} y {b.name} charlan y refuerzan su relacion.",
                citizen_ids=[a.id, b.id], building_id=building_id,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))

    async def talk_to_citizen(self, citizen_id: str, user_message: str, history: list[ChatMessage] | None = None) -> str:
        """Llamada real siempre (iniciada por el usuario, no por el motor de fondo)."""
        citizen = self.world.citizens.get(citizen_id)
        if citizen is None:
            raise KeyError(f"Ciudadano '{citizen_id}' no existe")
        provider = self._registry.get(citizen.provider)
        prompt = build_talk_prompt(citizen, self.world, history or [], user_message)
        try:
            text = (await provider.chat(prompt, citizen.model, temperature=0.8)).strip()
        except ProviderError as exc:
            text = f"[{citizen.name} no puede responder ahora mismo: {exc}]"
        if not text:
            text = "(sin respuesta)"
        citizen.remember(f"Un visitante me pregunto: «{user_message}» y le respondi: «{text}»")
        event = CityEvent.create(
            EventType.CONVERSACION, self.world.sim_day, self.world.sim_hour,
            f"Un visitante habla con {citizen.name}.",
            citizen_ids=[citizen.id], building_id=citizen.current_building_id,
        )
        self._record_event(event)
        await self._emit("city_event", self._event_payload(event))
        await self._store.save(self.world)
        return text

    async def save(self) -> None:
        await self._store.save(self.world)

    async def close(self) -> None:
        await self._store.close()

    def recent_events(self, limit: int = 50) -> list[dict]:
        return [self._event_payload(e) for e in self.world.recent_events(limit)]

    def snapshot(self) -> dict:
        """Estado completo, listo para JSON (misma serializacion que se usa
        para guardar a disco: ya no tiene enums ni datetimes sueltos)."""
        return world_to_dict(self.world)
