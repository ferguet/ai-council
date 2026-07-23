"""
El Director: un agente especial que NO responde al usuario, solo coordina.

Le pide a un modelo (configurable, por defecto "mock" para que funcione sin
key) que devuelva una decision estructurada en JSON sobre como debe
continuar el debate: quien habla a continuacion, si hay que resumir, si hay
consenso, si esta bloqueado, etc.

Si el modelo no devuelve JSON valido (pasa con modelos pequenos a veces),
hay una salvaguarda: round-robin + deteccion de repeticion por reglas, para
que el sistema nunca se quede colgado esperando una respuesta bien formada.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.domain.enums import DirectorAction
from app.domain.models import Agent, DebateSession
from app.providers.base import AIProvider, ChatMessage, ProviderError


@dataclass
class DirectorDecision:
    action: DirectorAction
    next_speaker_id: str | None
    reasoning: str


_DIRECTOR_SYSTEM_PROMPT = """Eres el Director de un consejo de inteligencias artificiales que debaten \
un tema. No participas en el debate ni das tu opinion sobre el tema: tu unico trabajo es coordinar.

En cada turno debes devolver EXCLUSIVAMENTE un JSON con esta forma, sin texto alrededor:
{{"action": "continue|summarize|end|request_evidence|ask_clarification|consensus|deadlock", \
"next_speaker_id": "<id_de_agente_o_null>", "reasoning": "<una frase breve explicando por que>"}}

Reglas para decidir:
- "continue": el debate avanza con normalidad, elige quien deberia hablar ahora (evita que \
el mismo participante hable dos veces seguidas salvo que le hayan preguntado algo directamente).
- "request_evidence": alguien ha hecho una afirmacion fuerte sin respaldo, pide pruebas.
- "ask_clarification": una postura es ambigua o contradictoria, pide que se aclare.
- "consensus": los participantes coinciden claramente en una conclusion.
- "deadlock": llevan varios turnos repitiendo lo mismo sin avanzar.
- "summarize": ya hay suficiente informacion para resumir antes de seguir.
- "end": se ha alcanzado consenso claro o el debate ya no aporta nada nuevo.

Participantes disponibles (id: nombre - rol):
{participants}
"""


class Director:
    def __init__(self, provider: AIProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    def _build_prompt(self, session: DebateSession) -> list[ChatMessage]:
        participants_desc = "\n".join(
            f"- {a.id}: {a.name} ({a.role})" for a in session.participants
        )
        system = _DIRECTOR_SYSTEM_PROMPT.format(participants=participants_desc)
        transcript = "\n".join(
            f"[{m.sender_name}] {m.content}" for m in session.recent_transcript()
        )
        user = f"Tema del debate: {session.topic}\n\nTranscripcion hasta ahora:\n{transcript or '(sin mensajes todavia)'}"
        return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _fallback_round_robin(self, session: DebateSession) -> DirectorDecision:
        """Salvaguarda si el modelo no devuelve JSON valido o falla la llamada."""
        if session.turn_count >= 10:
            return DirectorDecision(DirectorAction.END, None, "Limite de turnos de seguridad alcanzado (fallback).")
        if not session.messages:
            next_agent = session.participants[0]
        else:
            last_speaker_id = session.messages[-1].sender_id
            ids = [a.id for a in session.participants]
            if last_speaker_id in ids:
                idx = (ids.index(last_speaker_id) + 1) % len(ids)
            else:
                idx = 0
            next_agent = session.participants[idx]
        return DirectorDecision(DirectorAction.CONTINUE, next_agent.id, "Turno rotatorio (fallback sin IA).")

    async def decide(self, session: DebateSession) -> DirectorDecision:
        messages = self._build_prompt(session)
        try:
            raw = await self._provider.chat(messages, self._model, temperature=0.2)
        except ProviderError:
            return self._fallback_round_robin(session)

        data = self._extract_json(raw)
        if not data:
            return self._fallback_round_robin(session)

        try:
            action = DirectorAction(data.get("action", "continue"))
        except ValueError:
            action = DirectorAction.CONTINUE

        next_speaker_id = data.get("next_speaker_id")
        if next_speaker_id and session.get_agent(next_speaker_id) is None:
            next_speaker_id = None
        if action == DirectorAction.CONTINUE and next_speaker_id is None:
            return self._fallback_round_robin(session)

        return DirectorDecision(
            action=action,
            next_speaker_id=next_speaker_id,
            reasoning=str(data.get("reasoning", "")),
        )
