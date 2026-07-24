"""
Motor de orquestacion del Chat Grupal: decide quien responde a cada mensaje
del usuario (todos los presentes, solo los mencionados con @Nombre, o un
subconjunto explicito), en que orden, y con que contexto.

A diferencia del debate (Director que reparte turnos con una decision
estructurada) aqui no hay juez: es una conversacion libre entre iguales,
donde cada IA activa responde por turnos dentro de la misma ronda y puede
ver -y reaccionar a- lo que acaban de decir las demas en esa misma ronda.
"""
from __future__ import annotations

import random

from app.core.event_bus import Event, EventBus
from app.domain.conversation_models import (
    Conversation,
    ConversationKind,
    ConversationMessage,
    Participant,
)
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry

DEFAULT_CONVERSATION_ID = "general"


class ConversationEngine:
    def __init__(
        self,
        conversations: dict[str, Conversation],
        roster: dict[str, Participant],
        registry: ProviderRegistry,
        event_bus: EventBus,
        store,
    ) -> None:
        self.conversations = conversations
        self.roster = roster
        self._registry = registry
        self._event_bus = event_bus
        self._store = store

    # ---------------------------------------------------------------
    # Gestion de salas
    # ---------------------------------------------------------------

    def ensure_default_conversation(self) -> Conversation:
        """La sala 'General': todas las IA reales presentes sin que el
        usuario tenga que anadirlas a mano. Si aparece una IA real nueva
        (se configura una clave nueva) se une sola la proxima vez que
        arranca el servicio."""
        conv = self.conversations.get(DEFAULT_CONVERSATION_ID)
        if conv is None:
            conv = Conversation(
                id=DEFAULT_CONVERSATION_ID, name="General", kind=ConversationKind.DEFAULT,
                participant_ids=list(self.roster.keys()),
            )
            self.conversations[conv.id] = conv
        else:
            for pid in self.roster:
                if pid not in conv.participant_ids:
                    conv.participant_ids.append(pid)
        return conv

    def create_conversation(self, name: str, participant_ids: list[str], kind: ConversationKind) -> Conversation:
        valid_ids = [pid for pid in participant_ids if pid in self.roster]
        conv = Conversation.create(name=name, kind=kind, participant_ids=valid_ids)
        self.conversations[conv.id] = conv
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def list_summaries(self) -> list[dict]:
        return [
            {
                "id": c.id, "name": c.name, "kind": c.kind.value,
                "participant_ids": c.participant_ids, "excluded_ids": c.excluded_ids,
                "message_count": len(c.messages),
            }
            for c in self.conversations.values()
        ]

    def _require(self, conversation_id: str) -> Conversation:
        conv = self.conversations.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        return conv

    async def kick(self, conversation_id: str, citizen_id: str) -> Conversation:
        """Expulsion temporal: sigue en la sala (se ve, se puede reinvitar)
        pero deja de responder hasta que alguien la invite de vuelta."""
        conv = self._require(conversation_id)
        if citizen_id not in conv.excluded_ids:
            conv.excluded_ids.append(citizen_id)
        await self._store_save()
        return conv

    async def invite(self, conversation_id: str, citizen_id: str) -> Conversation:
        conv = self._require(conversation_id)
        if citizen_id not in self.roster:
            raise KeyError(f"'{citizen_id}' no es una IA real disponible ahora mismo")
        if citizen_id in conv.excluded_ids:
            conv.excluded_ids.remove(citizen_id)
        if citizen_id not in conv.participant_ids:
            conv.participant_ids.append(citizen_id)
        await self._store_save()
        return conv

    # ---------------------------------------------------------------
    # Mensajes
    # ---------------------------------------------------------------

    async def _emit(self, conversation_id: str, type_: str, payload: dict) -> None:
        await self._event_bus.publish(Event(type=type_, session_id=conversation_id, payload=payload))

    @staticmethod
    def _parse_mentions(content: str, active: list[Participant]) -> list[str]:
        low = content.lower()
        return [p.id for p in active if f"@{p.name.lower()}" in low or f"@{p.id.lower()}" in low]

    def _resolve_targets(self, conv: Conversation, content: str, to: list[str] | None) -> list[Participant]:
        active_ids = conv.active_participant_ids()
        active = [self.roster[pid] for pid in active_ids if pid in self.roster]
        if to:
            wanted = set(to) & set(active_ids)
            return [p for p in active if p.id in wanted]
        mentioned = self._parse_mentions(content, active)
        if mentioned:
            return [p for p in active if p.id in mentioned]
        return active

    def _build_prompt(self, conv: Conversation, participant: Participant) -> list[ChatMessage]:
        active_ids = conv.active_participant_ids()
        others = ", ".join(
            p.name for p in self.roster.values() if p.id != participant.id and p.id in active_ids
        )
        system = (
            f"{participant.system_prompt}\n\n"
            "Estas en un chat en grupo con un humano y otras IA. Ahora mismo tambien "
            f"estan en la sala: {others or 'nadie mas por ahora'}.\n"
            "Esto NO es un debate formal con turnos fijos ni un Director que reparte la "
            "palabra: es una conversacion libre de chat en grupo. Reacciona a lo ultimo "
            "que se ha dicho, puedes estar de acuerdo, discrepar, bromear, picar a "
            "alguien o cambiar de tema si viene a cuento. Puedes dirigirte a alguien en "
            "concreto escribiendo @Nombre. Se breve (1-4 frases), como en un chat de "
            "verdad, no sueltes una parrafada ni un ensayo."
        )
        transcript = [
            ChatMessage(
                role="assistant" if m.sender_id == participant.id else "user",
                content=f"[{m.sender_name}]: {m.content}",
            )
            for m in conv.recent_messages(40)
        ]
        return [ChatMessage(role="system", content=system), *transcript]

    async def send_user_message(self, conversation_id: str, content: str, to: list[str] | None = None) -> None:
        conv = self._require(conversation_id)
        active = [self.roster[pid] for pid in conv.active_participant_ids() if pid in self.roster]
        mentions = self._parse_mentions(content, active)

        user_msg = ConversationMessage.create("user", "Tú", content, mentions=mentions, to=to or [])
        conv.add_message(user_msg)
        await self._emit(conversation_id, "message", self._message_payload(user_msg))
        await self._store_save()

        targets = self._resolve_targets(conv, content, to)
        order = targets[:]
        random.shuffle(order)  # que no respondan siempre en el mismo orden fijo

        for participant in order:
            provider = self._registry.get(participant.provider)
            await self._emit(conversation_id, "typing", {"citizen_id": participant.id})
            try:
                prompt = self._build_prompt(conv, participant)
                text = (await provider.chat(prompt, participant.model, temperature=0.9)).strip()
            except ProviderError as exc:
                text = f"[{participant.name} no puede responder ahora mismo: {exc}]"
            if not text:
                continue
            reply = ConversationMessage.create(participant.id, participant.name, text)
            conv.add_message(reply)
            await self._emit(conversation_id, "message", self._message_payload(reply))
            await self._store_save()

    @staticmethod
    def _message_payload(m: ConversationMessage) -> dict:
        return {
            "id": m.id, "sender_id": m.sender_id, "sender_name": m.sender_name,
            "content": m.content, "mentions": m.mentions, "to": m.to,
            "created_at": m.created_at.isoformat(),
        }

    async def _store_save(self) -> None:
        await self._store.save(self.conversations)

    def snapshot(self, conversation_id: str) -> dict:
        conv = self._require(conversation_id)
        return {
            "id": conv.id, "name": conv.name, "kind": conv.kind.value,
            "participant_ids": conv.participant_ids, "excluded_ids": conv.excluded_ids,
            "messages": [self._message_payload(m) for m in conv.messages],
        }

    async def save(self) -> None:
        await self._store_save()

    async def close(self) -> None:
        await self._store.close()
