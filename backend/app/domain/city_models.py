"""
Modelos de dominio de la Ciudad Virtual (Persistent AI Civilization).

Mismo espiritu que domain/models.py: estructuras de datos puras, sin saber
nada de HTTP, WebSocket, JSON ni de como se ejecuta la simulacion. El motor
de simulacion (app/simulation/engine.py) es quien las mueve en el tiempo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.city_enums import ActivityType, BuildingType, EventType, ProjectStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def mood_label_for(happiness: int, anger: int) -> str:
    """Etiqueta (emoji + palabra) del estado de animo a partir de sus dos
    componentes. El enfado manda sobre la alegria si es alto."""
    if anger >= 60:
        return "😠 Cabreado/a"
    if anger >= 38:
        return "😤 Irritado/a"
    if happiness >= 78:
        return "🤩 Eufórico/a"
    if happiness >= 62:
        return "😄 Contento/a"
    if happiness >= 50:
        return "🙂 Animado/a"
    if happiness <= 28:
        return "😔 Bajón"
    if happiness <= 40:
        return "😕 Apagado/a"
    return "😐 Neutral"


@dataclass
class ScheduleBlock:
    """Un tramo de la rutina diaria de un ciudadano: de que hora a que hora,
    en que edificio, haciendo que."""

    start_hour: int          # 0-23, hora simulada de inicio (inclusive)
    end_hour: int             # 0-24, hora simulada de fin (exclusive)
    building_id: str
    activity: ActivityType
    label: str                # texto humano, p.ej. "Revisando literatura reciente"

    def contains(self, hour: int) -> bool:
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour  # cruza medianoche


@dataclass
class Relationship:
    """Relacion dirigida entre dos ciudadanos. Evoluciona con el tiempo, no
    es estatica: colaborar sube confianza/respeto, mucho tiempo sin
    interactuar los deja igual (no baja solos, de momento)."""

    trust: float = 0.5
    respect: float = 0.5
    collaborations: int = 0
    last_interaction: datetime | None = None

    def reinforce(self, trust_delta: float = 0.03, respect_delta: float = 0.02) -> None:
        self.trust = min(1.0, self.trust + trust_delta)
        self.respect = min(1.0, self.respect + respect_delta)
        self.collaborations += 1
        self.last_interaction = _now()


@dataclass
class Citizen:
    """Un ciudadano de la ciudad: una IA con vida propia (no solo un
    participante puntual de un debate). Vive, trabaja, tiene rutina,
    memoria propia y relaciones que persisten entre sesiones."""

    id: str
    name: str
    provider: str              # "anthropic" | "gemini" | "openai" | "groq" | "deepseek" | "glm" | "mock"
    model: str
    profession: str
    system_prompt: str
    color: str
    avatar: str                 # emoji, para pintarlo barato en el frontend
    home_id: str
    workplace_id: str
    schedule: list[ScheduleBlock] = field(default_factory=list)

    current_building_id: str = ""
    current_activity: ActivityType = ActivityType.DESCANSAR
    current_activity_label: str = "Descansando"
    current_project_id: str | None = None

    memory: list[str] = field(default_factory=list)   # diario personal, texto libre, capado
    relationships: dict[str, Relationship] = field(default_factory=dict)

    last_real_ai_call: datetime | None = None
    energy: float = 1.0

    # Estado de animo, que se puede "intuir" de lo que dice/piensa el ciudadano.
    # happiness = alegria (0-100), anger = enfado (0-100). mood_label es el
    # emoji+palabra que se muestra. Se actualiza cuando piensa o conversa.
    happiness: int = 55
    anger: int = 8
    mood_label: str = "😐 Neutral"

    def set_mood(self, happiness: int, anger: int) -> None:
        self.happiness = max(0, min(100, happiness))
        self.anger = max(0, min(100, anger))
        self.mood_label = mood_label_for(self.happiness, self.anger)

    def remember(self, entry: str, cap: int = 25) -> None:
        self.memory.append(entry)
        if len(self.memory) > cap:
            self.memory = self.memory[-cap:]

    def relationship_with(self, other_id: str) -> Relationship:
        if other_id not in self.relationships:
            self.relationships[other_id] = Relationship()
        return self.relationships[other_id]

    def schedule_for_hour(self, hour: int) -> ScheduleBlock | None:
        for block in self.schedule:
            if block.contains(hour):
                return block
        return None


@dataclass
class Building:
    id: str
    name: str
    type: BuildingType
    description: str
    icon: str          # emoji
    x: int              # posicion en la cuadricula del mapa (frontend)
    y: int

    def occupants(self, citizens: dict[str, Citizen]) -> list[Citizen]:
        return [c for c in citizens.values() if c.current_building_id == self.id]


@dataclass
class Project:
    id: str
    title: str
    description: str
    owner_ids: list[str]
    building_id: str | None
    status: ProjectStatus = ProjectStatus.ACTIVO
    progress: int = 0            # 0-100
    log: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(title: str, description: str, owner_ids: list[str], building_id: str | None) -> "Project":
        return Project(id=_new_id(), title=title, description=description,
                        owner_ids=owner_ids, building_id=building_id)

    def advance(self, amount: int, log_entry: str | None = None) -> None:
        self.progress = min(100, self.progress + amount)
        if log_entry:
            self.log.append(log_entry)
        if self.progress >= 100:
            self.status = ProjectStatus.COMPLETADO


@dataclass
class CityEvent:
    id: str
    type: EventType
    sim_day: int
    sim_hour: int
    citizen_ids: list[str]
    building_id: str | None
    description: str
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def create(type_: EventType, sim_day: int, sim_hour: int, description: str,
               citizen_ids: list[str] | None = None, building_id: str | None = None) -> "CityEvent":
        return CityEvent(id=_new_id(), type=type_, sim_day=sim_day, sim_hour=sim_hour,
                          citizen_ids=citizen_ids or [], building_id=building_id,
                          description=description)


@dataclass
class WorldState:
    """El mundo entero, en un momento dado. Es lo unico que se persiste a
    disco: con esto basta para reconstruir la ciudad completa al reiniciar."""

    citizens: dict[str, Citizen] = field(default_factory=dict)
    buildings: dict[str, Building] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    events: list[CityEvent] = field(default_factory=list)   # mas reciente al final, capado

    sim_day: int = 1
    sim_hour: int = 8
    tick_count: int = 0

    def add_event(self, event: CityEvent, cap: int = 500) -> None:
        self.events.append(event)
        if len(self.events) > cap:
            self.events = self.events[-cap:]

    def recent_events(self, limit: int = 50) -> list[CityEvent]:
        return self.events[-limit:]

    def sim_time_label(self) -> str:
        return f"Dia {self.sim_day}, {self.sim_hour:02d}:00"
