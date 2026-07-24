"""
Convierte el roster de ciudadanos de la Ciudad Virtual (world_data.py) en
la lista de Participants disponibles para el Chat Grupal.

Solo entran los que tienen una clave real configurada (is_configured() ==
True): nada simulado aparece nunca en la conversacion. Reutiliza los mismos
ciudadanos (misma personalidad "sin filtros") en vez de duplicar
personajes, para que quien hables en el chat sea la misma IA que vive en
la ciudad.
"""
from __future__ import annotations

from app.domain.conversation_models import Participant
from app.providers.registry import ProviderRegistry
from app.simulation.world_data import build_default_citizens


def build_active_roster(registry: ProviderRegistry) -> dict[str, Participant]:
    roster: dict[str, Participant] = {}
    for cid, citizen in build_default_citizens().items():
        provider = registry.get(citizen.provider)
        if not provider.is_configured():
            continue
        roster[cid] = Participant(
            id=citizen.id, name=citizen.name, provider=citizen.provider, model=citizen.model,
            avatar=citizen.avatar, color=citizen.color, system_prompt=citizen.system_prompt,
            profession=citizen.profession,
        )
    return roster
