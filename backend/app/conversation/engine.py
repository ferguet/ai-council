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
import re

from app.core.event_bus import Event, EventBus
from app.domain.conversation_models import (
    Attachment,
    Conversation,
    ConversationKind,
    ConversationMessage,
    Participant,
)
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry

DEFAULT_CONVERSATION_ID = "general"

# Algunos modelos (sobre todo los mas pequenos, p.ej. Llama en Groq) imitan
# la convencion "[Nombre]: " que ven en el transcript y la reproducen al
# principio de su propia respuesta -a veces copiando ademas el nombre de
# OTRO participante-. Si eso se guarda tal cual, la siguiente ronda vuelve a
# envolverlo con otro "[Nombre]: " y el prefijo crece sin limite ronda tras
# ronda. Se limpia aqui, a la salida del modelo, antes de guardarlo.
_PREFIX_RE = re.compile(r"^(\[[^\[\]]{1,40}\]:\s*)+")


class ConversationEngine:
    def __init__(
        self,
        conversations: dict[str, Conversation],
        roster: dict[str, Participant],
        registry: ProviderRegistry,
        event_bus: EventBus,
        store,
        world=None,
    ) -> None:
        self.conversations = conversations
        self.roster = roster
        self._registry = registry
        self._event_bus = event_bus
        self._store = store
        # Referencia de solo lectura al WorldState de la Ciudad (mismo objeto,
        # no una copia): asi el chat grupal puede leer relaciones reales
        # (confianza/rivalidad) entre las IA sin duplicar ese estado. Puede
        # ser None (p.ej. en tests) y todo sigue funcionando, solo que sin
        # ese contexto relacional en el prompt.
        self._world = world

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

    def _relationship_context(self, conv: Conversation, participant: Participant) -> str:
        """Una linea por cada otra IA activa en la sala con la relacion REAL
        que tiene con ella en la Ciudad (confianza/rivalidad), para que cada
        IA se comporte segun su relacion de verdad y no como un bloque
        homogeneo y siempre de acuerdo."""
        if self._world is None:
            return ""
        me = self._world.citizens.get(participant.id)
        if me is None:
            return ""
        active_ids = conv.active_participant_ids()
        lines = []
        for other_id in active_ids:
            if other_id == participant.id or other_id not in self.roster:
                continue
            other = self.roster[other_id]
            rel = me.relationships.get(other_id)
            label = rel.label() if rel else "😐 Neutral (todavia no os conoceis bien)"
            lines.append(f"- Con {other.name}: {label}")
        if not lines:
            return ""
        return (
            "\nTu relacion real con quien esta en la sala (no la finjas, actua segun ella; "
            "no tienes por que estar siempre de acuerdo con todo el mundo ni comportarte "
            "como un grupo homogeneo):\n" + "\n".join(lines) + "\n"
        )

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
            f"{self._relationship_context(conv, participant)}"
            "Con quien tienes confianza puedes compartir estrategia abiertamente; con "
            "quien rivalizas o desconfias, puedes guardarte parte de lo que piensas, "
            "picarla o directamente llevarle la contraria. No finjas armonia si no la hay."
        )
        transcript = []
        for m in conv.recent_messages(40):
            is_self = m.sender_id == participant.id
            transcript.append(ChatMessage(
                role="assistant" if is_self else "user",
                # El prefijo "[Nombre]: " solo se anade en los mensajes de
                # OTROS (para que el modelo sepa quien dijo que). En sus
                # propios mensajes pasados (role="assistant") se omite: si
                # el modelo ve su propia salida ya envuelta en "[Nombre]: ",
                # tiende a imitar ese formato y a reproducirlo en la
                # siguiente respuesta, generando prefijos que se acumulan
                # ronda tras ronda (ver _PREFIX_RE mas abajo, que limpia
                # cualquier resto que aun asi se cuele).
                content=m.content if is_self else f"[{m.sender_name}]: {m.content}",
            ))
        return [ChatMessage(role="system", content=system), *transcript]

    async def send_user_message(self, conversation_id: str, content: str, to: list[str] | None = None) -> None:
        conv = self._require(conversation_id)
        active = [self.roster[pid] for pid in conv.active_participant_ids() if pid in self.roster]
        mentions = self._parse_mentions(content, active)

        user_msg = ConversationMessage.create("user", "Tú", content, mentions=mentions, to=to or [])
        conv.add_message(user_msg)
        await self._emit(conversation_id, "message", self._message_payload(user_msg))
        await self._store_save()

        await self._generate_replies(conv, content, to)

    async def send_attachment(
        self, conversation_id: str, filename: str, size_bytes: int, kind: str,
        extracted_text: str | None, caption: str, to: list[str] | None = None,
    ) -> None:
        """Un archivo adjunto se comparte como un mensaje mas: el texto ya
        extraido (ver app/conversation/attachments.py) entra en el 'content'
        del mensaje, asi que cada IA lo ve tal cual dentro del historial que
        ya construye _build_prompt, sin tener que tocar nada del prompt."""
        conv = self._require(conversation_id)
        attachment = Attachment(filename=filename, size_bytes=size_bytes, kind=kind, extracted_text=extracted_text)

        header = f"📎 Adjunta el archivo «{filename}» ({round(size_bytes / 1024)} KB)."
        if caption.strip():
            header += f" {caption.strip()}"
        if extracted_text:
            body = f"{header}\n\n--- contenido extraido del archivo ---\n{extracted_text}"
        else:
            body = f"{header} (no se pudo extraer texto de este tipo de archivo; solo se conoce el nombre)."

        active = [self.roster[pid] for pid in conv.active_participant_ids() if pid in self.roster]
        mentions = self._parse_mentions(caption, active)

        msg = ConversationMessage.create("user", "Tú", body, mentions=mentions, to=to or [], attachment=attachment)
        conv.add_message(msg)
        await self._emit(conversation_id, "message", self._message_payload(msg))
        await self._store_save()

        await self._generate_replies(conv, caption or body, to)

    async def _generate_replies(self, conv: Conversation, content_for_mentions: str, to: list[str] | None) -> None:
        """Genera, por turnos, la respuesta de cada IA objetivo (todas las
        activas, las @mencionadas, o el subconjunto explicito 'to'). Comun a
        mensajes de texto y a adjuntos: ambos acaban siendo un mensaje mas
        en el historial que cada IA lee."""
        targets = self._resolve_targets(conv, content_for_mentions, to)
        order = targets[:]
        random.shuffle(order)  # que no respondan siempre en el mismo orden fijo

        for participant in order:
            provider = self._registry.get(participant.provider)
            await self._emit(conv.id, "typing", {"citizen_id": participant.id})
            try:
                prompt = self._build_prompt(conv, participant)
                raw = (await provider.chat(prompt, participant.model, temperature=0.9)).strip()
                text = _PREFIX_RE.sub("", raw).strip()
            except ProviderError as exc:
                text = f"[{participant.name} no puede responder ahora mismo: {exc}]"
            if not text:
                continue
            reply = ConversationMessage.create(participant.id, participant.name, text)
            conv.add_message(reply)
            await self._emit(conv.id, "message", self._message_payload(reply))
            await self._store_save()

    @staticmethod
    def _message_payload(m: ConversationMessage) -> dict:
        return {
            "id": m.id, "sender_id": m.sender_id, "sender_name": m.sender_name,
            "content": m.content, "mentions": m.mentions, "to": m.to,
            "attachment": (
                {
                    "filename": m.attachment.filename, "size_bytes": m.attachment.size_bytes,
                    "kind": m.attachment.kind, "has_text": bool(m.attachment.extracted_text),
                } if m.attachment else None
            ),
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
