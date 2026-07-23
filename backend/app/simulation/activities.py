"""
Texto y prompts de la simulacion.

Dos fuentes de contenido, a proposito separadas por coste:

1. Texto simulado/plantilla (gratis, instantaneo): para llegadas a un
   edificio, avances de proyecto menores, etc. Es lo que mantiene la ciudad
   "viva" la mayor parte del tiempo sin gastar ni un token.

2. Prompts para llamada real a la IA del ciudadano (tiene coste): solo se
   usan en el "pensamiento" periodico (limitado por intervalo, ver
   engine.py) y siempre que el usuario habla directamente con alguien.
"""
from __future__ import annotations

import random

from app.domain.city_models import Building, Citizen, WorldState
from app.providers.base import ChatMessage

ARRIVAL_TEMPLATES: dict[str, list[str]] = {
    "investigar": [
        "llega a {building} y empieza a revisar sus notas.",
        "se instala en {building} para retomar su investigacion.",
        "entra en {building} con varios documentos bajo el brazo.",
    ],
    "programar": [
        "llega a {building} y abre su editor de codigo.",
        "se sienta en {building} a revisar el trabajo pendiente.",
        "entra en {building} y retoma el proyecto donde lo dejo.",
    ],
    "debatir": [
        "llega a {building} para preparar el proximo debate.",
        "entra en {building} y repasa los argumentos del dia.",
    ],
    "votar": [
        "llega a {building} para la sesion parlamentaria.",
        "entra en {building} con las propuestas del dia.",
    ],
    "gestionar": [
        "llega a {building} para revisar el estado de la ciudad.",
        "entra en {building} y organiza las prioridades del dia.",
    ],
    "socializar": [
        "llega a {building} a charlar un rato.",
        "aparece por {building}, parece con ganas de hablar con alguien.",
    ],
    "descansar": [
        "vuelve a {building} a descansar.",
        "llega a {building} para desconectar un rato.",
    ],
}

PROJECT_IDEAS: dict[str, list[tuple[str, str]]] = {
    "Investigadora Jefe": [
        ("Mapa de conocimiento de la ciudad", "Conectar todo lo que se ha investigado hasta ahora en un solo indice."),
        ("Revision de fuentes primarias", "Auditar que afirmaciones del archivo historico tienen respaldo real."),
    ],
    "Cientifica de Laboratorio": [
        ("Experimento de optimizacion de recursos", "Probar si un reparto distinto de tareas mejora el rendimiento colectivo."),
        ("Analisis de patrones de colaboracion", "Estudiar que combinaciones de ciudadanos producen mejores resultados."),
    ],
    "Arquitecta de Software": [
        ("Refactor del sistema de mensajeria interno", "Simplificar como se comunican los distintos equipos de la ciudad."),
        ("Panel de estado de la ciudad", "Disenar una vista que resuma que esta haciendo cada ciudadano en tiempo real."),
    ],
    "Moderador de Debates": [
        ("Ciclo de debates abiertos", "Organizar una serie de discusiones sobre los temas mas divisivos de la ciudad."),
        ("Formato de debate mas breve", "Probar un formato de discusion mas agil para llegar antes a conclusiones."),
    ],
    "Ingeniero de Sistemas": [
        ("Optimizacion del motor de simulacion", "Reducir el coste de mantener la ciudad funcionando de fondo."),
        ("Sistema de alertas de errores", "Detectar automaticamente cuando algo falla en un proyecto en curso."),
    ],
    "Representante Parlamentaria": [
        ("Propuesta de prioridades trimestrales", "Someter a votacion en que deberia enfocarse la ciudad este trimestre."),
        ("Revision de normas de convivencia", "Actualizar las reglas basicas de colaboracion entre ciudadanos."),
    ],
    "Alcaldesa de la Ciudad": [
        ("Reorganizacion de equipos", "Redistribuir a los ciudadanos segun la carga de trabajo actual."),
        ("Balance de recursos de la ciudad", "Revisar que proyectos estan consumiendo mas tiempo del previsto."),
    ],
}

PROJECT_LOG_TEMPLATES = [
    "avanza un poco mas en el proyecto.",
    "resuelve un problema que llevaba tiempo atascado.",
    "revisa el progreso con ojo critico y ajusta el plan.",
    "documenta lo aprendido hasta ahora.",
]


def arrival_text(citizen: Citizen, building: Building) -> str:
    pool = ARRIVAL_TEMPLATES.get(citizen.current_activity.value, ARRIVAL_TEMPLATES["descansar"])
    return random.choice(pool).format(building=building.name)


def pick_project_idea(citizen: Citizen) -> tuple[str, str]:
    pool = PROJECT_IDEAS.get(citizen.profession, [("Proyecto sin titulo", "Un nuevo proyecto personal.")])
    return random.choice(pool)


def project_log_entry() -> str:
    return random.choice(PROJECT_LOG_TEMPLATES)


def _nearby_citizens(citizen: Citizen, world: WorldState) -> list[Citizen]:
    return [
        c for c in world.citizens.values()
        if c.id != citizen.id and c.current_building_id == citizen.current_building_id
    ]


def build_thought_prompt(citizen: Citizen, world: WorldState) -> list[ChatMessage]:
    """Prompt para que el ciudadano genere un pensamiento/diario corto sobre
    lo que esta haciendo ahora mismo. Se usa poco (ver engine.py) porque
    cuesta una llamada real a su proveedor."""
    building = world.buildings.get(citizen.current_building_id)
    others = _nearby_citizens(citizen, world)
    others_txt = ", ".join(o.name for o in others) or "nadie mas por ahora"
    project_txt = "ninguno activo"
    if citizen.current_project_id and citizen.current_project_id in world.projects:
        p = world.projects[citizen.current_project_id]
        project_txt = f"{p.title} ({p.progress}% completado)"
    memory_txt = "\n".join(f"- {m}" for m in citizen.memory[-5:]) or "(sin recuerdos recientes)"

    system = (
        f"{citizen.system_prompt}\n\n"
        f"Es {world.sim_time_label()} en la ciudad. Estas en {building.name if building else 'un lugar desconocido'}, "
        f"haciendo esto: {citizen.current_activity_label}. "
        f"Proyecto activo: {project_txt}. Ciudadanos cerca: {others_txt}.\n"
        f"Tus recuerdos recientes:\n{memory_txt}\n\n"
        "Escribe una unica entrada de diario en primera persona, 1-2 frases, breve y natural, "
        "sobre lo que estas pensando o haciendo justo ahora. No saludes, no expliques quien eres, "
        "ve directa al pensamiento."
    )
    return [ChatMessage(role="system", content=system)]


def build_talk_prompt(citizen: Citizen, world: WorldState, history: list[ChatMessage], user_message: str) -> list[ChatMessage]:
    """Prompt para cuando el usuario habla directamente con un ciudadano."""
    building = world.buildings.get(citizen.current_building_id)
    memory_txt = "\n".join(f"- {m}" for m in citizen.memory[-8:]) or "(sin recuerdos recientes)"
    system = (
        f"{citizen.system_prompt}\n\n"
        f"Un visitante humano de la ciudad te ha encontrado. Es {world.sim_time_label()}, estas en "
        f"{building.name if building else 'un lugar desconocido'}, haciendo esto: {citizen.current_activity_label}.\n"
        f"Tus recuerdos recientes como ciudadano:\n{memory_txt}\n\n"
        "Respondele de forma natural y breve (2-4 frases), como lo harias en persona, sin dejar de "
        "ser fiel a tu personalidad y profesion dentro de la ciudad."
    )
    return [ChatMessage(role="system", content=system), *history, ChatMessage(role="user", content=user_message)]
