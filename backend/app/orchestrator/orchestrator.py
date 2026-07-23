"""
El Orchestrator ejecuta el bucle de debate: en cada turno pregunta al
Director quien debe hablar y con que proposito, llama a ese agente (con
streaming, publicando cada trozo en el Event Bus), guarda el mensaje en la
sesion, y decide si continuar, resumir o terminar segun lo que diga el
Director. Tambien permite que el usuario intervenga en cualquier momento.
"""
from __future__ import annotations

from app.core.event_bus import Event, EventBus
from app.domain.enums import DebateStatus, DirectorAction, MessageType
from app.domain.models import Agent, DebateSession, Message
from app.orchestrator.director import Director, DirectorDecision
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry


class Orchestrator:
    def __init__(
        self,
        registry: ProviderRegistry,
        event_bus: EventBus,
        director: Director,
        max_turns: int = 20,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._director = director
        self._max_turns = max_turns

    def _build_agent_context(self, session: DebateSession, agent: Agent, decision: DirectorDecision) -> list[ChatMessage]:
        others = ", ".join(a.name for a in session.participants if a.id != agent.id)
        shared_facts = "\n".join(f"- {f.content}" for f in session.shared_memory) or "(ninguno todavia)"
        system = (
            f"{agent.system_prompt}\n\n"
            f"Participas en un debate junto a: {others}. "
            f"Tema del debate: {session.topic}\n"
            f"Hechos/decisiones aceptados por el consejo hasta ahora:\n{shared_facts}\n\n"
            "Responde de forma breve y con tu propia postura (2-4 frases). "
            "Si estas en desacuerdo con algo dicho antes, dilo explicitamente y explica por que. "
            "Si el Director te ha pedido pruebas o una aclaracion, atiende a eso directamente."
        )
        transcript = [
            ChatMessage(
                role="assistant" if m.sender_id == agent.id else "user",
                content=f"[{m.sender_name}]: {m.content}",
            )
            for m in session.recent_transcript()
        ]
        director_note = ""
        if decision.action == DirectorAction.REQUEST_EVIDENCE:
            director_note = "\n(El Director te pide pruebas o fuentes para tu siguiente intervencion.)"
        elif decision.action == DirectorAction.ASK_CLARIFICATION:
            director_note = "\n(El Director te pide que aclares tu postura, hay ambiguedad.)"
        if director_note:
            transcript.append(ChatMessage(role="user", content=director_note.strip()))
        return [ChatMessage(role="system", content=system), *transcript]

    async def _emit(self, session_id: str, type_: str, payload: dict) -> None:
        await self._event_bus.publish(Event(type=type_, session_id=session_id, payload=payload))

    async def _run_agent_turn(self, session: DebateSession, agent: Agent, decision: DirectorDecision) -> Message:
        provider = self._registry.get(agent.provider)
        context = self._build_agent_context(session, agent, decision)

        await self._emit(session.id, "agent_typing", {"agent_id": agent.id, "agent_name": agent.name})

        chunks: list[str] = []
        try:
            async for chunk in provider.stream_chat(context, agent.model):
                chunks.append(chunk)
                await self._emit(
                    session.id,
                    "agent_chunk",
                    {"agent_id": agent.id, "agent_name": agent.name, "chunk": chunk},
                )
        except ProviderError as exc:
            error_text = f"[No se pudo obtener respuesta de {agent.name}: {exc}]"
            await self._emit(session.id, "agent_error", {"agent_id": agent.id, "error": str(exc)})
            message = Message.create(agent.id, agent.name, error_text, MessageType.SYSTEM)
            session.add_message(message)
            return message

        content = "".join(chunks).strip() or "(sin respuesta)"
        message = Message.create(agent.id, agent.name, content, MessageType.STATEMENT)
        session.add_message(message)
        await self._emit(
            session.id,
            "agent_message_complete",
            {"agent_id": agent.id, "agent_name": agent.name, "message_id": message.id, "content": content},
        )
        return message

    async def add_user_message(self, session: DebateSession, content: str) -> None:
        message = Message.create("user", "Tú", content, MessageType.USER)
        session.add_message(message)
        await self._emit(session.id, "user_message", {"content": content})

    async def run_until_pause_or_end(self, session: DebateSession) -> None:
        """
        Ejecuta turnos hasta que el Director decida terminar, se alcance el
        limite de seguridad, o la sesion pase a PAUSED (el llamador puede
        pausar entre turnos, p.ej. si el usuario quiere intervenir).
        """
        while session.status == DebateStatus.ACTIVE and session.turn_count < self._max_turns:
            decision = await self._director.decide(session)
            await self._emit(
                session.id,
                "director_decision",
                {"action": decision.action.value, "reasoning": decision.reasoning,
                 "next_speaker_id": decision.next_speaker_id},
            )

            if decision.action in (DirectorAction.END, DirectorAction.CONSENSUS, DirectorAction.DEADLOCK):
                session.status = (
                    DebateStatus.CONSENSUS_REACHED if decision.action == DirectorAction.CONSENSUS
                    else DebateStatus.DEADLOCKED if decision.action == DirectorAction.DEADLOCK
                    else DebateStatus.ENDED
                )
                if decision.reasoning:
                    session.add_shared_fact(decision.reasoning, "director")
                await self._emit(session.id, "debate_ended", {"status": session.status.value})
                break

            if decision.action == DirectorAction.SUMMARIZE:
                session.add_message(
                    Message.create("director", "Director", decision.reasoning, MessageType.SUMMARY)
                )
                await self._emit(session.id, "summary", {"content": decision.reasoning})
                continue

            speaker_id = decision.next_speaker_id
            agent = session.get_agent(speaker_id) if speaker_id else None
            if agent is None:
                break  # salvaguarda extra: sin orador valido, no seguimos en bucle

            await self._run_agent_turn(session, agent, decision)
            session.turn_count += 1

        if session.turn_count >= self._max_turns and session.status == DebateStatus.ACTIVE:
            session.status = DebateStatus.ENDED
            await self._emit(session.id, "debate_ended", {"status": "ended", "reason": "max_turns"})
