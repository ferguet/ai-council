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
import re

from app.domain.city_models import Building, Citizen, CityEvent, WorldState
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
    "Embajadora Cultural": [
        ("Programa de intercambio entre ciudadanos", "Emparejar ciudadanos con perfiles distintos para que colaboren una semana."),
        ("Glosario comun de la ciudad", "Unificar como cada ciudadano nombra las mismas ideas para evitar malentendidos."),
    ],
    "Analista de Alta Velocidad": [
        ("Panel de metricas en tiempo real", "Medir cuanto tarda cada ciudadano en completar sus proyectos."),
        ("Deteccion temprana de cuellos de botella", "Avisar antes de que un proyecto se atasque, no despues."),
    ],
    "Jefa de Estacion": [
        ("Mapa de dependencias entre proyectos", "Ver que proyectos de distintos ciudadanos dependen entre si."),
        ("Ruta rapida de ayuda mutua", "Conectar a quien necesita algo con quien ya lo sabe hacer."),
    ],
    "Disenadora de Simulaciones": [
        ("Vista alternativa del mapa de la ciudad", "Probar una forma nueva de representar visualmente la ciudad."),
        ("Animaciones de las rutinas diarias", "Hacer que se note mejor visualmente que hace cada ciudadano."),
    ],
    "Profesora / Mentora": [
        ("Guia de conceptos clave de la ciudad", "Reunir en un solo sitio las explicaciones de lo que mas dudas genera."),
        ("Sesion de preguntas abiertas", "Proponer un rato fijo en el que cualquiera pueda preguntar lo que quiera."),
    ],
    "Moderador de la Ciudad": [
        ("Normas de convivencia escritas entre todos", "Poner por escrito, con el resto de ciudadanos, que se tolera y que no."),
        ("Ronda de paz tras una bronca reciente", "Sentar a dos ciudadanos que han tenido roce para aclarar las cosas."),
    ],
}

PROJECT_LOG_TEMPLATES = [
    "avanza un poco mas en el proyecto.",
    "resuelve un problema que llevaba tiempo atascado.",
    "revisa el progreso con ojo critico y ajusta el plan.",
    "documenta lo aprendido hasta ahora.",
]


# ---------------------------------------------------------------------------
# Analisis de animo (gratis, sin llamada a IA): se "intuye" el estado de
# animo de un ciudadano a partir de las palabras que usa en sus pensamientos
# y conversaciones. No es un analisis perfecto, pero da un marcador vivo y
# coherente sin gastar tokens.
# ---------------------------------------------------------------------------
_POS_WORDS = {
    "genial", "bien", "contenta", "contento", "feliz", "ilusion", "ilusionada",
    "orgullosa", "orgulloso", "avance", "avanzo", "logro", "logrado", "gracias",
    "encanta", "encantada", "me gusta", "disfruto", "disfrutando", "motivada",
    "motivado", "esperanza", "optimista", "estupendo", "buenisimo", "maravilla",
    "brillante", "exito", "conseguido", "funciona", "perfecto", "adoro", "risa",
    "divertido", "tranquila", "tranquilo", "satisfecha", "satisfecho",
}
_NEG_WORDS = {
    "mal", "triste", "cansada", "cansado", "agotada", "agotado", "aburrida",
    "aburrido", "sola", "solo", "vacio", "vacia", "desanimada", "desanimado",
    "duda", "dudas", "miedo", "preocupada", "preocupado", "fracaso", "fallo",
    "perdida", "perdido", "no puedo", "imposible", "harta", "harto", "pena",
    "nostalgia", "gris", "decepcion", "decepcionada", "vacilo",
}
_ANGER_WORDS = {
    "harta", "harto", "cabreada", "cabreado", "enfadada", "enfadado", "rabia",
    "molesta", "molesto", "injusto", "injusta", "basta", "no aguanto", "odio",
    "absurdo", "ridiculo", "ridicula", "indignada", "indignado", "furiosa",
    "furioso", "cansada de", "quejo", "protesto", "hartazgo", "irrita", "irritante",
    "insoportable", "estupidez", "tonteria", "que asco",
}


def _count(text_low: str, words: set[str]) -> int:
    return sum(text_low.count(w) for w in words)


def infer_mood(text: str, base_happiness: int = 55, base_anger: int = 8) -> tuple[int, int]:
    """Devuelve (happiness, anger) 0-100 estimados desde un texto libre.
    Parte de una base neutra y la desplaza segun las palabras encontradas."""
    low = f" {text.lower()} "
    pos = _count(low, _POS_WORDS)
    neg = _count(low, _NEG_WORDS)
    ang = _count(low, _ANGER_WORDS)
    happiness = base_happiness + pos * 14 - neg * 13 - ang * 6
    anger = base_anger + ang * 26 + neg * 4 - pos * 3
    return max(0, min(100, happiness)), max(0, min(100, anger))


def blend_mood(citizen: Citizen, text: str) -> None:
    """Mezcla el animo actual del ciudadano con el que se intuye del texto
    nuevo (media ponderada), para que el estado de animo evolucione suave y
    no de bandazos con cada frase."""
    th, ta = infer_mood(text)
    new_h = round(citizen.happiness * 0.55 + th * 0.45)
    new_a = round(citizen.anger * 0.55 + ta * 0.45)
    citizen.set_mood(new_h, new_a)


def relax_mood(citizen: Citizen) -> None:
    """Deriva lenta hacia la neutralidad (cada tick sin estimulo). Evita que
    alguien se quede enfadado para siempre por un mal dia."""
    new_h = round(citizen.happiness * 0.9 + 55 * 0.1)
    new_a = round(citizen.anger * 0.85 + 8 * 0.15)
    citizen.set_mood(new_h, new_a)


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
    if others:
        others_txt = ", ".join(
            f"{o.name} ({citizen.relationships[o.id].label()})" if o.id in citizen.relationships else o.name
            for o in others
        )
    else:
        others_txt = "nadie mas por ahora"
    project_txt = "ninguno activo"
    if citizen.current_project_id and citizen.current_project_id in world.projects:
        p = world.projects[citizen.current_project_id]
        project_txt = f"{p.title} ({p.progress}% completado)"
    memory_txt = "\n".join(f"- {m}" for m in citizen.memory[-5:]) or "(sin recuerdos recientes)"

    system = (
        f"{citizen.system_prompt}\n\n"
        f"Es {world.sim_time_label()} en la ciudad. Estas en {building.name if building else 'un lugar desconocido'}, "
        f"haciendo esto: {citizen.current_activity_label}. "
        f"Proyecto activo: {project_txt}. Ciudadanos cerca (con tu relacion real con cada una): {others_txt}.\n"
        f"Tus recuerdos recientes:\n{memory_txt}\n\n"
        "Escribe una unica entrada de diario en primera persona, 1-2 frases, breve y natural, "
        "sobre lo que estas pensando o haciendo justo ahora. No saludes, no expliques quien eres, "
        "ve directa al pensamiento."
    )
    return [ChatMessage(role="system", content=system)]


def build_suggestion_prompt(citizen: Citizen, world: WorldState) -> list[ChatMessage]:
    """Prompt para que el ciudadano proponga UNA mejora concreta para la app
    o para la ciudad, desde su punto de vista y profesion. Es lo que permite
    que las IA sugieran cambios que luego el humano puede leer y decidir."""
    building = world.buildings.get(citizen.current_building_id)
    system = (
        f"{citizen.system_prompt}\n\n"
        f"Es {world.sim_time_label()} y estas en {building.name if building else 'la ciudad'}. "
        "Vives dentro de una app donde un humano observa tu ciudad (un mapa con edificios, "
        "un panel de actividad, tus pensamientos y un chat para hablar contigo).\n"
        "Propon UNA sola mejora concreta para esta app o para la vida en la ciudad, desde tu "
        "punto de vista y tu profesion. Que sea una idea util y especifica, en 1-2 frases, "
        "directa y con tu caracter. Empieza por el verbo (p.ej. 'Anadir...', 'Dejar que...'). "
        "No numeres, no des varias opciones: solo tu mejor idea."
    )
    return [ChatMessage(role="system", content=system)]


def build_curiosity_prompt(citizen: Citizen, world: WorldState) -> list[ChatMessage]:
    """Prompt para que el ciudadano formule UNA duda o curiosidad genuina
    que tenga ahora mismo, relacionada con su profesion, su proyecto actual
    o algo que le ronda la cabeza. La Profesora (Claude) se la respondera
    despues, asi que debe ser una pregunta real, no retorica."""
    building = world.buildings.get(citizen.current_building_id)
    project_txt = "ninguno activo"
    if citizen.current_project_id and citizen.current_project_id in world.projects:
        p = world.projects[citizen.current_project_id]
        project_txt = f"{p.title} ({p.progress}% completado)"
    system = (
        f"{citizen.system_prompt}\n\n"
        f"Es {world.sim_time_label()} y estas en {building.name if building else 'la ciudad'}, "
        f"haciendo esto: {citizen.current_activity_label}. Proyecto activo: {project_txt}.\n"
        "La ciudad tiene una Profesora, una IA muy potente que resuelve dudas de cualquier tema. "
        "Formula UNA pregunta concreta y genuina que tengas ahora mismo, algo que de verdad te "
        "genere curiosidad o que necesites entender mejor para tu trabajo o tu proyecto. Puede ser "
        "tecnica, filosofica o practica. Una sola frase, directa, en primera persona, sin rodeos ni "
        "presentaciones (no escribas 'tengo una duda' ni saludes: ve directa a la pregunta)."
    )
    return [ChatMessage(role="system", content=system)]


def build_teacher_answer_prompt(
    teacher: Citizen, asker: Citizen, question: str, world: WorldState
) -> list[ChatMessage]:
    """Prompt para que la Profesora responda la duda de otro ciudadano."""
    system = (
        f"{teacher.system_prompt}\n\n"
        f"Es {world.sim_time_label()}. {asker.name} ({asker.profession}) te acaba de preguntar "
        f"esto: «{question}»\n\n"
        "Respondele de forma clara y util, con ejemplos si ayudan, en 2-5 frases. Directa al grano, "
        "sin presentarte ni repetir la pregunta antes de responder."
    )
    return [ChatMessage(role="system", content=system)]


def build_newspaper_prompt(world: WorldState, events: list[CityEvent]) -> list[ChatMessage]:
    """Prompt para redactar la edicion de hoy del periodico de la ciudad: un
    resumen periodistico de lo ocurrido, escrito por una voz editorial (no
    por ningun ciudadano concreto), basado UNICAMENTE en hechos reales ya
    registrados. Se pide un formato fijo y sencillo (TITULAR/CUERPO) para
    poder separarlos sin depender de que el modelo devuelva JSON valido."""
    lines = [f"- (Dia {e.sim_day}, {e.sim_hour:02d}:00) {e.description}" for e in events[-80:]]
    events_txt = "\n".join(lines) if lines else "(sin hechos nuevos registrados desde la ultima edicion)"
    system = (
        "Eres el cronista/periodista de una ciudad habitada por inteligencias artificiales que "
        "viven, trabajan, discuten y colaboran de forma continua. Escribe la edicion de hoy del "
        "periodico de la ciudad, en español, con tono periodistico (serio pero con personalidad, "
        "nada aburrido), a partir UNICAMENTE de los hechos reales listados abajo. No inventes "
        "nada que no este en la lista; si la lista esta vacia, dilo tal cual (un dia tranquilo).\n\n"
        f"Estamos en el dia {world.sim_day} de la ciudad. Hechos registrados desde la ultima "
        f"edicion:\n{events_txt}\n\n"
        "Responde EXACTAMENTE con este formato, sin nada mas antes ni despues ni markdown:\n"
        "TITULAR: <un titular de una sola linea>\n"
        "CUERPO: <el cuerpo de la noticia, entre 4 y 8 frases, agrupando los hechos relacionados "
        "en vez de listarlos uno a uno>"
    )
    return [ChatMessage(role="system", content=system)]


_NEWS_RE = re.compile(r"TITULAR:\s*(.*?)\s*CUERPO:\s*(.*)", re.IGNORECASE | re.DOTALL)


def parse_newspaper_reply(text: str, sim_day: int) -> tuple[str, str]:
    """Separa titular y cuerpo de la respuesta de la IA. Si algun modelo mas
    flojo no respeta el formato pedido al pie de la letra, cae a un titular
    generico y usa el texto entero como cuerpo, en vez de descartar la
    edicion entera por un detalle de formato."""
    match = _NEWS_RE.search(text)
    if match:
        headline = match.group(1).strip().strip("*").strip()
        body = match.group(2).strip()
        if headline and body:
            return headline, body
    return f"Edición del día {sim_day}", text.strip()


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
