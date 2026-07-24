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
    blend_mood,
    build_curiosity_prompt,
    build_suggestion_prompt,
    build_talk_prompt,
    build_teacher_answer_prompt,
    build_thought_prompt,
    pick_project_idea,
    project_log_entry,
    relax_mood,
)
from app.simulation.persistence import WorldStore, world_to_dict

CITY_SESSION_ID = "city-world"
TEACHER_ID = "profesora"

# Probabilidades por tick, deliberadamente bajas: la ciudad debe sentirse
# viva pero sin que cada tick sea un aluvion de eventos.
_PROJECT_START_CHANCE = 0.15
_PROJECT_ADVANCE_CHANCE = 0.4
_SOCIAL_REINFORCE_CHANCE = 0.3
# De los encuentros sociales, cuantos acaban en friccion en vez de cordialidad
# (base; sube con la rivalidad ya existente, baja con la confianza ya existente:
# las relaciones tienen memoria, no tiran un dado limpio cada vez).
_FRICTION_BASE_CHANCE = 0.28
# De los proyectos que se inician, en cuantos se invita a colaborar a alguien
# de mucha confianza en vez de emprenderlo en solitario.
_COLLAB_INVITE_CHANCE = 0.35
_TRUST_FOR_COLLAB = 0.7
# Cuando a un ciudadano le toca una llamada real, con esta probabilidad en
# vez de un pensamiento suelta una sugerencia de mejora para la app.
_SUGGESTION_CHANCE = 0.30
# ...y con esta otra, en vez de un pensamiento normal, formula una duda real
# que la Profesora (Claude) le resuelve justo despues. Se resta de la franja
# que le queda al pensamiento normal (no se suma a la de sugerencia).
_CURIOSITY_CHANCE = 0.20


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

            # A veces, en vez de emprenderlo sola, invita a colaborar a quien
            # mas confianza le inspira (si esa persona anda libre ahora mismo).
            # Asi las alianzas se traducen en algo concreto, no solo en un numero.
            partner = None
            trusted = sorted(
                (
                    (self.world.citizens[oid], rel)
                    for oid, rel in citizen.relationships.items()
                    if rel.trust >= _TRUST_FOR_COLLAB and oid in self.world.citizens
                ),
                key=lambda t: t[1].trust, reverse=True,
            )
            for candidate, _rel in trusted:
                if not candidate.current_project_id or candidate.current_project_id not in self.world.projects:
                    partner = candidate
                    break
            invite_partner = partner is not None and random.random() < _COLLAB_INVITE_CHANCE

            owner_ids = [citizen.id, partner.id] if invite_partner else [citizen.id]
            project = Project.create(title, description, owner_ids, citizen.current_building_id)
            self.world.projects[project.id] = project
            citizen.current_project_id = project.id

            if invite_partner:
                partner.current_project_id = project.id
                citizen.relationship_with(partner.id).reinforce(trust_delta=0.05, respect_delta=0.04)
                partner.relationship_with(citizen.id).reinforce(trust_delta=0.05, respect_delta=0.04)
                citizen.remember(f"{self.world.sim_time_label()}: inicie '{title}' junto a {partner.name}, en quien confio.")
                partner.remember(f"{self.world.sim_time_label()}: {citizen.name} me invito a colaborar en '{title}'.")
                description_text = f"{citizen.name} inicia un nuevo proyecto junto a {partner.name}: {title}."
                event_citizen_ids = [citizen.id, partner.id]
            else:
                citizen.remember(f"{self.world.sim_time_label()}: inicie el proyecto '{title}'.")
                description_text = f"{citizen.name} inicia un nuevo proyecto: {title}."
                event_citizen_ids = [citizen.id]

            event = CityEvent.create(
                EventType.PROYECTO_INICIADO, self.world.sim_day, self.world.sim_hour,
                description_text, citizen_ids=event_citizen_ids, building_id=citizen.current_building_id,
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
            relax_mood(citizen)  # mientras duerme se le va pasando el humor del dia
            return  # no gastamos llamadas reales mientras duermen
        provider = self._registry.get(citizen.provider)
        if not provider.is_configured():
            return
        now = datetime.now(timezone.utc)
        if citizen.last_real_ai_call and (now - citizen.last_real_ai_call) < self._real_ai_interval:
            return

        citizen.last_real_ai_call = now  # se marca antes de llamar: evita reintentos en bucle si falla
        roll = random.random()
        is_suggestion = roll < _SUGGESTION_CHANCE
        is_curiosity = (
            not is_suggestion
            and roll < _SUGGESTION_CHANCE + _CURIOSITY_CHANCE
            and citizen.id != TEACHER_ID  # la Profesora no se pregunta dudas a si misma
            and self._teacher_available()
        )
        try:
            if is_suggestion:
                prompt = build_suggestion_prompt(citizen, self.world)
            elif is_curiosity:
                prompt = build_curiosity_prompt(citizen, self.world)
            else:
                prompt = build_thought_prompt(citizen, self.world)
            text = (await provider.chat(prompt, citizen.model, temperature=0.9)).strip()
        except ProviderError:
            return
        if not text:
            return

        blend_mood(citizen, text)  # el animo se intuye de lo que acaba de decir
        if is_suggestion:
            citizen.remember(f"Propuse una mejora para la app: {text}")
            event = CityEvent.create(
                EventType.SUGERENCIA, self.world.sim_day, self.world.sim_hour,
                f"{citizen.name} sugiere: “{text}”",
                citizen_ids=[citizen.id], building_id=citizen.current_building_id,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))
        elif is_curiosity:
            citizen.remember(f"Le pregunte a la Profesora: {text}")
            event = CityEvent.create(
                EventType.DUDA, self.world.sim_day, self.world.sim_hour,
                f"{citizen.name}: “{text}”",
                citizen_ids=[citizen.id], building_id=citizen.current_building_id,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))
            await self._teacher_answer(citizen, text)
        else:
            citizen.remember(text)
            event = CityEvent.create(
                EventType.PENSAMIENTO, self.world.sim_day, self.world.sim_hour,
                f"{citizen.name}: “{text}”",
                citizen_ids=[citizen.id], building_id=citizen.current_building_id,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))

    def _teacher_available(self) -> bool:
        teacher = self.world.citizens.get(TEACHER_ID)
        if teacher is None:
            return False
        return self._registry.get(teacher.provider).is_configured()

    async def _teacher_answer(self, asker: Citizen, question: str) -> None:
        """La Profesora (Claude) responde a la duda que acaba de formular
        otro ciudadano. Llamada real siempre, sin pasar por el intervalo de
        la Profesora: resolver dudas es su trabajo, no un pensamiento suelto."""
        teacher = self.world.citizens.get(TEACHER_ID)
        if teacher is None:
            return
        provider = self._registry.get(teacher.provider)
        if not provider.is_configured():
            return
        try:
            prompt = build_teacher_answer_prompt(teacher, asker, question, self.world)
            text = (await provider.chat(prompt, teacher.model, temperature=0.6)).strip()
        except ProviderError:
            return
        if not text:
            return
        blend_mood(teacher, text)
        teacher.remember(f"Le respondi una duda a {asker.name}: «{question}» -> «{text}»")
        event = CityEvent.create(
            EventType.RESPUESTA_PROFESORA, self.world.sim_day, self.world.sim_hour,
            text, citizen_ids=[teacher.id, asker.id], building_id=teacher.current_building_id,
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
            rel = a.relationship_with(b.id)
            # La relacion previa tiene memoria: si ya hay rivalidad, es mas
            # facil que vuelva a haber roce; si ya hay confianza alta, es mas
            # dificil. No es un dado limpio cada vez.
            friction_chance = max(0.05, min(0.75, _FRICTION_BASE_CHANCE + rel.rivalry * 0.4 - rel.trust * 0.25))
            if random.random() < friction_chance:
                a.relationship_with(b.id).clash()
                b.relationship_with(a.id).clash()
                text = random.choice([
                    f"{a.name} y {b.name} discrepan abiertamente y la conversación se tensa.",
                    f"{a.name} y {b.name} chocan de opiniones; ninguna cede terreno.",
                    f"{a.name} pone en duda algo que dice {b.name}, y la cosa no sienta bien.",
                ])
            else:
                a.relationship_with(b.id).reinforce()
                b.relationship_with(a.id).reinforce()
                text = random.choice([
                    f"{a.name} y {b.name} charlan y refuerzan su relación.",
                    f"{a.name} y {b.name} conectan enseguida, se nota buena sintonía.",
                    f"{a.name} y {b.name} se ríen juntas de algo, ambiente distendido.",
                ])
            event = CityEvent.create(
                EventType.RELACION, self.world.sim_day, self.world.sim_hour, text,
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
        blend_mood(citizen, text)
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
