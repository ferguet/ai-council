"""
Persistencia del WorldState en disco (JSON).

La ciudad tiene que seguir existiendo aunque se reinicie el servidor: si al
arrancar hay un world_state.json guardado, se carga tal cual (con toda la
memoria, relaciones y proyectos de cada ciudadano). Si no existe, se
construye desde cero con app.simulation.world_data.build_default_world().

Se escribe con fichero temporal + os.replace para que un corte de luz a
mitad de escritura no deje el JSON corrupto.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.domain.city_enums import ActivityType, BuildingType, EventType, ProjectStatus
from app.domain.city_models import (
    Building,
    Citizen,
    CityEvent,
    Project,
    Relationship,
    ScheduleBlock,
    WorldState,
)


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _str_to_dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def world_to_dict(world: WorldState) -> dict:
    return {
        "sim_day": world.sim_day,
        "sim_hour": world.sim_hour,
        "tick_count": world.tick_count,
        "buildings": {
            bid: {
                "id": b.id, "name": b.name, "type": b.type.value, "description": b.description,
                "icon": b.icon, "x": b.x, "y": b.y,
            }
            for bid, b in world.buildings.items()
        },
        "citizens": {
            cid: {
                "id": c.id, "name": c.name, "provider": c.provider, "model": c.model,
                "profession": c.profession, "system_prompt": c.system_prompt,
                "color": c.color, "avatar": c.avatar,
                "home_id": c.home_id, "workplace_id": c.workplace_id,
                "schedule": [
                    {"start_hour": s.start_hour, "end_hour": s.end_hour, "building_id": s.building_id,
                     "activity": s.activity.value, "label": s.label}
                    for s in c.schedule
                ],
                "current_building_id": c.current_building_id,
                "current_activity": c.current_activity.value,
                "current_activity_label": c.current_activity_label,
                "current_project_id": c.current_project_id,
                "memory": c.memory,
                "relationships": {
                    other_id: {
                        "trust": r.trust, "respect": r.respect, "collaborations": r.collaborations,
                        "last_interaction": _dt_to_str(r.last_interaction),
                    }
                    for other_id, r in c.relationships.items()
                },
                "last_real_ai_call": _dt_to_str(c.last_real_ai_call),
                "energy": c.energy,
            }
            for cid, c in world.citizens.items()
        },
        "projects": {
            pid: {
                "id": p.id, "title": p.title, "description": p.description,
                "owner_ids": p.owner_ids, "building_id": p.building_id,
                "status": p.status.value, "progress": p.progress, "log": p.log,
                "created_at": _dt_to_str(p.created_at),
            }
            for pid, p in world.projects.items()
        },
        "events": [
            {
                "id": e.id, "type": e.type.value, "sim_day": e.sim_day, "sim_hour": e.sim_hour,
                "citizen_ids": e.citizen_ids, "building_id": e.building_id,
                "description": e.description, "created_at": _dt_to_str(e.created_at),
            }
            for e in world.events
        ],
    }


def world_from_dict(data: dict) -> WorldState:
    buildings = {
        bid: Building(id=b["id"], name=b["name"], type=BuildingType(b["type"]),
                      description=b["description"], icon=b["icon"], x=b["x"], y=b["y"])
        for bid, b in data.get("buildings", {}).items()
    }
    citizens = {}
    for cid, c in data.get("citizens", {}).items():
        schedule = [
            ScheduleBlock(start_hour=s["start_hour"], end_hour=s["end_hour"],
                          building_id=s["building_id"], activity=ActivityType(s["activity"]),
                          label=s["label"])
            for s in c.get("schedule", [])
        ]
        relationships = {
            other_id: Relationship(trust=r["trust"], respect=r["respect"],
                                    collaborations=r["collaborations"],
                                    last_interaction=_str_to_dt(r.get("last_interaction")))
            for other_id, r in c.get("relationships", {}).items()
        }
        citizens[cid] = Citizen(
            id=c["id"], name=c["name"], provider=c["provider"], model=c["model"],
            profession=c["profession"], system_prompt=c["system_prompt"],
            color=c["color"], avatar=c["avatar"], home_id=c["home_id"],
            workplace_id=c["workplace_id"], schedule=schedule,
            current_building_id=c.get("current_building_id", ""),
            current_activity=ActivityType(c.get("current_activity", "descansar")),
            current_activity_label=c.get("current_activity_label", ""),
            current_project_id=c.get("current_project_id"),
            memory=c.get("memory", []), relationships=relationships,
            last_real_ai_call=_str_to_dt(c.get("last_real_ai_call")),
            energy=c.get("energy", 1.0),
        )
    projects = {
        pid: Project(
            id=p["id"], title=p["title"], description=p["description"],
            owner_ids=p["owner_ids"], building_id=p.get("building_id"),
            status=ProjectStatus(p.get("status", "activo")), progress=p.get("progress", 0),
            log=p.get("log", []),
            created_at=_str_to_dt(p.get("created_at")) or datetime.now(timezone.utc),
        )
        for pid, p in data.get("projects", {}).items()
    }
    events = [
        CityEvent(
            id=e["id"], type=EventType(e["type"]), sim_day=e["sim_day"], sim_hour=e["sim_hour"],
            citizen_ids=e.get("citizen_ids", []), building_id=e.get("building_id"),
            description=e["description"],
            created_at=_str_to_dt(e.get("created_at")) or datetime.now(timezone.utc),
        )
        for e in data.get("events", [])
    ]
    return WorldState(
        citizens=citizens, buildings=buildings, projects=projects, events=events,
        sim_day=data.get("sim_day", 1), sim_hour=data.get("sim_hour", 8),
        tick_count=data.get("tick_count", 0),
    )


class WorldStore:
    """Guarda el WorldState en un fichero JSON local.

    Los metodos son 'async def' aunque el trabajo es sincrono (I/O local es
    rapido) para que esta clase sea intercambiable con PostgresWorldStore
    (persistence_pg.py) sin que el resto del codigo tenga que saber cual de
    las dos esta usando."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def exists(self) -> bool:
        return self._path.exists()

    async def load(self) -> WorldState:
        with open(self._path, "r", encoding="utf-8") as f:
            return world_from_dict(json.load(f))

    async def save(self, world: WorldState) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(world_to_dict(world), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)

    async def close(self) -> None:
        pass
