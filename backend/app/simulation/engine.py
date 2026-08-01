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
from app.domain.city_models import Citizen, CityEvent, NewsEdition, Project, WorldState
from app.providers.base import ChatMessage, ProviderError
from app.providers.circuit_breaker import ProviderCircuitBreaker
from app.providers.registry import ProviderRegistry
from app.providers.usage_tracker import ProviderUsageTracker
from app.simulation.activities import (
    arrival_text,
    blend_mood,
    build_curiosity_prompt,
    build_newspaper_prompt,
    build_suggestion_prompt,
    build_talk_prompt,
    build_teacher_answer_prompt,
    build_thought_prompt,
    parse_newspaper_reply,
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
        idle_pause_minutes: int = 30,
        news_provider: str = "glm",
        news_model: str = "glm-4.7-flash",
        news_interval_hours: int = 24,
        news_fallback_provider: str | None = "cerebras",
        news_fallback_model: str = "gpt-oss-120b",
        breaker: ProviderCircuitBreaker | None = None,
        usage: ProviderUsageTracker | None = None,
    ) -> None:
        self.world = world
        self._registry = registry
        self._event_bus = event_bus
        self._store = store
        # IMPORTANTE: estas dos instancias deben ser las MISMAS que usan
        # ConversationEngine/GuardianService/Interprete (se pasan desde
        # main.py). Antes cada uno tenia su propio contador y su propio
        # circuito, todos mirando las MISMAS claves de proveedor sin
        # enterarse del gasto real de los demas -la Ciudad podia agotar la
        # cuota real de un proveedor en segundo plano mientras el contador
        # del Chat Grupal seguia marcando "0 usadas hoy", y el chat se
        # quedaba mudo al chocar con un 429 real. Con instancias compartidas,
        # todos ven el mismo consumo y el mismo circuito.
        self._breaker = breaker or ProviderCircuitBreaker()
        self._usage = usage or ProviderUsageTracker()
        self._hours_per_tick = hours_per_tick
        self._real_ai_interval = timedelta(minutes=real_ai_interval_minutes)
        # Ahorro de cuota: si nadie se ha asomado a la ciudad en este rato, los
        # ciudadanos dejan de "pensar" con IA real. La ciudad NO se congela: el
        # reloj sigue, se mueven por sus horarios y el humor evoluciona -todo eso
        # es gratis. Lo unico que se pausa son las llamadas de pago, que es donde
        # se iba la cuota corriendo 24/7 sin que nadie mirase. En cuanto alguien
        # abre la app vuelven a pensar en el siguiente tick (~1 min).
        # Con 0 se desactiva la pausa y la ciudad piensa siempre, como antes.
        self._idle_pause = timedelta(minutes=idle_pause_minutes) if idle_pause_minutes > 0 else None
        self.last_viewer_at: datetime | None = None
        self.live_viewers = 0  # WebSockets abiertos ahora mismo sobre /ws/city
        self._news_provider = news_provider
        self._news_model = news_model
        self._news_interval = timedelta(hours=news_interval_hours)
        self._news_fallback_provider = news_fallback_provider
        self._news_fallback_model = news_fallback_model
        self.last_news_error: str | None = None  # motivo de la ultima generacion fallida/omitida

    def note_viewer(self) -> None:
        """Alguien esta mirando la ciudad ahora mismo (abrio la pagina o se
        conecto por WebSocket). Reactiva los pensamientos con IA real si
        estaban pausados por inactividad."""
        self.last_viewer_at = datetime.now(timezone.utc)

    def viewer_connected(self) -> None:
        self.live_viewers += 1
        self.note_viewer()

    def viewer_disconnected(self) -> None:
        self.live_viewers = max(0, self.live_viewers - 1)
        self.note_viewer()  # cuenta como visita reciente: da margen antes de pausar

    def is_idle(self) -> bool:
        """True si no hay nadie mirando y toca ahorrar cuota."""
        if self._idle_pause is None:
            return False
        if self.live_viewers > 0:
            return False  # hay alguien con la ciudad abierta en vivo
        if self.last_viewer_at is None:
            return True
        return (datetime.now(timezone.utc) - self.last_viewer_at) > self._idle_pause

    async def _guarded_chat(
        self, provider, provider_name: str, prompt, model: str, temperature: float,
    ) -> str:
        """Igual que llamar a provider.chat(...) pero pasando por el mismo
        control de cuota/circuito que el resto de la app (ver comentario en
        __init__). Si el proveedor esta racionado o con el circuito abierto,
        lanza ProviderError sin gastar ni un intento real -asi la Ciudad deja
        de consumir en silencio la cuota que necesita el Chat Grupal."""
        if self._breaker.is_open(provider_name):
            raise ProviderError(f"circuito abierto para '{provider_name}'")
        if self._usage.is_near_limit(provider_name):
            raise ProviderError(f"'{provider_name}' racionado por hoy")
        self._usage.record_call(provider_name)
        try:
            text = await provider.chat(
                # Subido de 180 a 300 por el mismo motivo que _CHAT_MAX_TOKENS:
                # un pensamiento cortado a la mitad cuesta lo mismo que uno
                # entero y no aporta nada al historial de la ciudad.
                prompt, model, temperature=temperature, max_tokens=300,
            )
        except ProviderError:
            self._breaker.record_failure(provider_name)
            raise
        self._breaker.record_success(provider_name)
        return text

    async def _emit(self, type_: str, payload: dict) -> None:
        await self._event_bus.publish(Event(type=type_, session_id=CITY_SESSION_ID, payload=payload))

    @staticmethod
    def _event_payload(event: CityEvent) -> dict:
        return {
            "id": event.id, "type": event.type.value, "sim_day": event.sim_day,
            "sim_hour": event.sim_hour, "citizen_ids": event.citizen_ids,
            "building_id": event.building_id, "description": event.description,
            "reasoning": event.reasoning,
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
        await self.generate_news_edition()

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
            partner_rel = None
            for candidate, rel_candidate in trusted:
                if not candidate.current_project_id or candidate.current_project_id not in self.world.projects:
                    partner = candidate
                    partner_rel = rel_candidate
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
                reasoning = (
                    f"{citizen.name} confía en {partner.name} (confianza {partner_rel.trust:.0%}), "
                    "por eso le ha invitado en vez de ir por libre."
                )
            else:
                citizen.remember(f"{self.world.sim_time_label()}: inicie el proyecto '{title}'.")
                description_text = f"{citizen.name} inicia un nuevo proyecto: {title}."
                event_citizen_ids = [citizen.id]
                reasoning = (
                    f"Podría haber invitado a {partner.name} (confianza {partner_rel.trust:.0%}), "
                    "pero esta vez ha preferido ir por libre."
                ) if partner is not None else None

            event = CityEvent.create(
                EventType.PROYECTO_INICIADO, self.world.sim_day, self.world.sim_hour,
                description_text, citizen_ids=event_citizen_ids, building_id=citizen.current_building_id,
                reasoning=reasoning,
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
        if self.is_idle():
            return  # nadie mirando: se pausan las llamadas de pago (ver note_viewer)
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
            text = (
                await self._guarded_chat(provider, citizen.provider, prompt, citizen.model, 0.9)
            ).strip()
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
            text = (
                await self._guarded_chat(provider, teacher.provider, prompt, teacher.model, 0.6)
            ).strip()
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
            # Se guarda el trust/rivalry de ANTES de tocar la relacion: es lo
            # que explica por que ha pasado esto, no el resultado ya mutado.
            prev_trust, prev_rivalry = rel.trust, rel.rivalry
            # La relacion previa tiene memoria: si ya hay rivalidad, es mas
            # facil que vuelva a haber roce; si ya hay confianza alta, es mas
            # dificil. No es un dado limpio cada vez.
            friction_chance = max(0.05, min(0.75, _FRICTION_BASE_CHANCE + prev_rivalry * 0.4 - prev_trust * 0.25))
            if random.random() < friction_chance:
                a.relationship_with(b.id).clash()
                b.relationship_with(a.id).clash()
                text = random.choice([
                    f"{a.name} y {b.name} discrepan abiertamente y la conversación se tensa.",
                    f"{a.name} y {b.name} chocan de opiniones; ninguna cede terreno.",
                    f"{a.name} pone en duda algo que dice {b.name}, y la cosa no sienta bien.",
                ])
                if prev_rivalry >= 0.4:
                    reasoning = f"Ya había rivalidad previa entre ambas ({prev_rivalry:.0%}); no hacía falta mucho para que saltara chispa."
                elif prev_trust <= 0.35:
                    reasoning = f"Apenas se tenían confianza de antes ({prev_trust:.0%}), terreno abonado para el roce."
                else:
                    reasoning = "No había motivo de fondo: ha sido un choque puntual, no algo que vinieran arrastrando."
            else:
                a.relationship_with(b.id).reinforce()
                b.relationship_with(a.id).reinforce()
                text = random.choice([
                    f"{a.name} y {b.name} charlan y refuerzan su relación.",
                    f"{a.name} y {b.name} conectan enseguida, se nota buena sintonía.",
                    f"{a.name} y {b.name} se ríen juntas de algo, ambiente distendido.",
                ])
                if prev_trust >= 0.65:
                    reasoning = f"Ya se tenían confianza de antes ({prev_trust:.0%}); la conversación ha ido rodada."
                else:
                    reasoning = f"Todavía no se conocían mucho (confianza {prev_trust:.0%} antes de esto), pero ha salido mejor de lo esperado."
            event = CityEvent.create(
                EventType.RELACION, self.world.sim_day, self.world.sim_hour, text,
                citizen_ids=[a.id, b.id], building_id=building_id, reasoning=reasoning,
            )
            self._record_event(event)
            await self._emit("city_event", self._event_payload(event))

    @staticmethod
    def _news_payload(edition: NewsEdition) -> dict:
        return {
            "id": edition.id, "sim_day": edition.sim_day, "headline": edition.headline,
            "body": edition.body, "created_at": edition.created_at.isoformat(),
        }

    def _events_since_last_news(self) -> list[CityEvent]:
        if self.world.last_news_at is None:
            return self.world.events[-80:]
        return [e for e in self.world.events if e.created_at > self.world.last_news_at]

    async def generate_news_edition(self, force: bool = False) -> NewsEdition | None:
        """Genera una edicion nueva del periodico si toca (cada
        news_interval_hours) y hay hechos nuevos que contar, o siempre que
        force=True (boton de 'generar ahora' del usuario). Devuelve la
        edicion nueva, o None si no se genero nada (ni tocaba, ni habia
        proveedor listo, ni hubo respuesta)."""
        now = datetime.now(timezone.utc)
        # Nota: el periodico NO se pausa por inactividad, a proposito. Es una
        # sola llamada cada 24h, no es donde se iba la cuota, y asi al volver
        # a abrir la app te encuentras la prensa al dia.
        if not force and self.world.last_news_at and (now - self.world.last_news_at) < self._news_interval:
            self.last_news_error = "Todavía no toca (no ha pasado el intervalo configurado)."
            return None
        events = self._events_since_last_news()
        if not events and not force:
            self.last_news_error = "No hay hechos nuevos que contar desde la última edición."
            return None
        provider = self._registry.get(self._news_provider)
        model = self._news_model
        if not provider.is_configured():
            self.last_news_error = f"El proveedor de noticias '{self._news_provider}' no está configurado."
            return None
        prompt = build_newspaper_prompt(self.world, events)
        try:
            text = (
                await self._guarded_chat(provider, self._news_provider, prompt, model, 0.7)
            ).strip()
        except ProviderError as exc:
            primary_error = str(exc)
            fallback = self._news_fallback_provider
            # El periodico no tiene "personaje" propio (a diferencia de los
            # ciudadanos, que SI son una IA concreta): si el proveedor
            # principal se queda sin cuota, probar una vez con el de
            # reserva antes de perder la edicion del dia entero.
            if not fallback or fallback == self._news_provider:
                self.last_news_error = primary_error
                return None
            fallback_provider = self._registry.get(fallback)
            if not fallback_provider.is_configured():
                self.last_news_error = primary_error
                return None
            try:
                text = (
                    await self._guarded_chat(
                        fallback_provider, fallback, prompt, self._news_fallback_model, 0.7,
                    )
                ).strip()
            except ProviderError:
                # El error que interesa reportar es el del proveedor
                # principal (el configurado "de verdad" para este rol); el
                # de reserva era solo un segundo intento silencioso.
                self.last_news_error = primary_error
                return None
        if not text:
            self.last_news_error = "El proveedor de noticias devolvió una respuesta vacía."
            return None
        headline, body = parse_newspaper_reply(text, self.world.sim_day)
        edition = NewsEdition.create(self.world.sim_day, headline, body)
        self.world.add_news(edition)
        self.world.last_news_at = now
        self.last_news_error = None
        await self._store.save(self.world)
        await self._emit("news_edition", self._news_payload(edition))
        return edition

    def recent_news(self, limit: int = 20) -> list[dict]:
        """Ediciones mas recientes primero, listas para el frontend."""
        return [self._news_payload(n) for n in reversed(self.world.news[-limit:])]

    async def talk_to_citizen(self, citizen_id: str, user_message: str, history: list[ChatMessage] | None = None) -> str:
        """Llamada real siempre (iniciada por el usuario, no por el motor de fondo)."""
        citizen = self.world.citizens.get(citizen_id)
        if citizen is None:
            raise KeyError(f"Ciudadano '{citizen_id}' no existe")
        self.note_viewer()  # hablar con un ciudadano cuenta como estar mirando
        provider = self._registry.get(citizen.provider)
        prompt = build_talk_prompt(citizen, self.world, history or [], user_message)
        try:
            text = (
                await self._guarded_chat(provider, citizen.provider, prompt, citizen.model, 0.8)
            ).strip()
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

    # Cuanto historial viaja al navegador en la foto inicial. La vista de
    # actividad ya solo pinta los 50 ultimos, y pensamientos/ideas/aula
    # filtran sobre lo que haya: con 300 eventos van servidas de sobra. Sin
    # este tope la foto crecia sin freno (nunca se borra un evento), y como
    # se manda ENTERA en cada conexion, un movil reconectando se llevaba por
    # delante el ancho de banda del mes. Ver _SNAPSHOT_* mas abajo.
    _SNAPSHOT_MAX_EVENTS = 300
    _SNAPSHOT_MAX_NEWS = 30
    _SNAPSHOT_MAX_MEMORY = 10  # la ficha del ciudadano enseña las 5 ultimas
    _SNAPSHOT_MAX_LOG = 10

    def snapshot(self) -> dict:
        """Foto del mundo para MANDAR AL NAVEGADOR. Ojo: no es lo mismo que
        lo que se guarda en disco.

        world_to_dict() se usa tambien para persistir, y ahi hay que
        guardarlo TODO. Aqui, en cambio, se recorta lo que el navegador no
        necesita, porque esta foto se manda entera cada vez que alguien
        abre la Ciudad o se le reconecta el WebSocket:

        - system_prompt: es la personalidad de cada IA, texto largo (la
          mitad del peso total) que el frontend no lee en ningun sitio.
        - direct_messages: se piden aparte cuando se abre una conversacion
          (/city/citizens/{a}/messages/{b}), no hacen falta de entrada.
        - events/news/memory/log: solo lo reciente (ver _SNAPSHOT_MAX_*).

        Nada de esto se pierde: sigue entero en el mundo y en disco.
        """
        data = world_to_dict(self.world)

        data["events"] = data.get("events", [])[-self._SNAPSHOT_MAX_EVENTS:]
        data["news"] = data.get("news", [])[-self._SNAPSHOT_MAX_NEWS:]
        data["direct_messages"] = []

        for citizen in data.get("citizens", {}).values():
            citizen.pop("system_prompt", None)
            citizen["memory"] = citizen.get("memory", [])[-self._SNAPSHOT_MAX_MEMORY:]

        for project in data.get("projects", {}).values():
            project["log"] = project.get("log", [])[-self._SNAPSHOT_MAX_LOG:]

        return data
