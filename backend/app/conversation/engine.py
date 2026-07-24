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

import asyncio
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
from app.providers.circuit_breaker import ProviderCircuitBreaker
from app.providers.registry import ProviderRegistry
from app.providers.usage_tracker import ProviderUsageTracker

DEFAULT_CONVERSATION_ID = "general"

# Proveedor + modelo de respaldo por proveedor principal: si el proveedor de
# un ciudadano falla de verdad (excepcion) o tiene el circuito abierto (ver
# ProviderCircuitBreaker), se prueba UNA vez con este proveedor alternativo
# antes de dar el turno por perdido -misma personalidad (el prompt ya lleva
# su system_prompt de siempre), solo cambia quien "presta la voz" ese turno.
# Elegidos para que cada proveedor tenga como respaldo uno DISTINTO (no
# comparten cuota entre si) y con capa gratuita ya probada en esta app.
# Idea de la ciudadana "Kimi" en el Chat Grupal (24/07): "modelos locales de
# respaldo en cada piso de la torre, para cuando la nube de turno se vaya a
# dormir" -aqui no hay modelos locales, pero el equivalente real que SI
# podemos ofrecer es un proveedor de respaldo por ciudadano.
_FALLBACK_PROVIDER: dict[str, tuple[str, str]] = {
    "gemini": ("groq", "llama-3.3-70b-versatile"),
    "gemini2": ("groq", "llama-3.3-70b-versatile"),
    "groq": ("cerebras", "gpt-oss-120b"),
    "glm": ("openrouter", "openai/gpt-oss-20b:free"),
    "mistral": ("openrouter", "openai/gpt-oss-20b:free"),
    "openrouter": ("groq", "llama-3.3-70b-versatile"),
    "nvidia": ("groq", "llama-3.3-70b-versatile"),
    "cerebras": ("groq", "llama-3.3-70b-versatile"),
    "deepseek": ("openrouter", "openai/gpt-oss-20b:free"),
    "openai": ("openrouter", "openai/gpt-oss-20b:free"),
    "anthropic": ("openrouter", "openai/gpt-oss-20b:free"),
}

# El Moderador no tiene por que hablar en cada ronda: solo cuando de verdad
# hace falta calmar una bronca o le mencionan. Si decide que no hace falta
# intervenir, se le pide que conteste EXACTAMENTE con este texto, y ese
# turno se descarta sin publicar nada (ver _build_prompt y _generate_replies).
MODERATOR_ID = "moderador"
_SILENCE_TOKEN = "[SIN INTERVENIR]"

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
        breaker: ProviderCircuitBreaker | None = None,
        usage: ProviderUsageTracker | None = None,
    ) -> None:
        self.conversations = conversations
        self.roster = roster
        self._registry = registry
        self._event_bus = event_bus
        self._store = store
        # Un circuito por proveedor (no por ciudadano: varios ciudadanos
        # pueden compartir proveedor y cuota, p.ej. Profesora y Moderador en
        # "gemini2"). Inyectable para tests; en produccion usa los valores
        # por defecto (3 fallos seguidos -> 3 min abierto).
        self._breaker = breaker or ProviderCircuitBreaker()
        # Racionamiento diario por proveedor: igual que el breaker, uno solo
        # compartido por proveedor (no por ciudadano). Inyectable para
        # tests; en produccion usa el tope de settings.provider_daily_soft_cap.
        self._usage = usage or ProviderUsageTracker()
        # Referencia de solo lectura al WorldState de la Ciudad (mismo objeto,
        # no una copia): asi el chat grupal puede leer relaciones reales
        # (confianza/rivalidad) entre las IA sin duplicar ese estado. Puede
        # ser None (p.ej. en tests) y todo sigue funcionando, solo que sin
        # ese contexto relacional en el prompt.
        self._world = world

    # ---------------------------------------------------------------
    # Gestion de salas
    # ---------------------------------------------------------------

    def _default_conversation_id(self, visitor_id: str) -> str:
        return f"{DEFAULT_CONVERSATION_ID}-{visitor_id}"

    def ensure_default_conversation(self, visitor_id: str) -> Conversation:
        """La sala 'General' DE ESE VISITANTE: todas las IA reales
        presentes sin que tenga que anadirlas a mano. Cada visitante (ver
        app/core/access.py) tiene la suya propia, no comparten historial
        entre ellos. Si aparece una IA real nueva (se configura una clave
        nueva) se une sola la proxima vez que ese visitante entra."""
        conv_id = self._default_conversation_id(visitor_id)
        conv = self.conversations.get(conv_id)
        if conv is None:
            conv = Conversation(
                id=conv_id, name="General", kind=ConversationKind.DEFAULT,
                participant_ids=list(self.roster.keys()), owner_visitor_id=visitor_id,
            )
            self.conversations[conv.id] = conv
        else:
            for pid in self.roster:
                if pid not in conv.participant_ids:
                    conv.participant_ids.append(pid)
        return conv

    def create_conversation(
        self, name: str, participant_ids: list[str], kind: ConversationKind, owner_visitor_id: str,
    ) -> Conversation:
        valid_ids = [pid for pid in participant_ids if pid in self.roster]
        conv = Conversation.create(name=name, kind=kind, participant_ids=valid_ids, owner_visitor_id=owner_visitor_id)
        self.conversations[conv.id] = conv
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        return self.conversations.get(conversation_id)

    def get_owned(self, conversation_id: str, visitor_id: str) -> Conversation | None:
        """Como get(), pero solo devuelve la sala si es de ese visitante.
        Salas antiguas sin dueno (owner_visitor_id=None, de antes de que
        existiera la puerta de acceso) se tratan como inaccesibles: nadie
        las reclama automaticamente para evitar que un visitante cualquiera
        termine viendo historial que no es suyo."""
        conv = self.conversations.get(conversation_id)
        if conv is None or conv.owner_visitor_id != visitor_id:
            return None
        return conv

    def list_summaries(self, visitor_id: str) -> list[dict]:
        return [
            {
                "id": c.id, "name": c.name, "kind": c.kind.value,
                "participant_ids": c.participant_ids, "excluded_ids": c.excluded_ids,
                "message_count": len(c.messages),
            }
            for c in self.conversations.values()
            if c.owner_visitor_id == visitor_id
        ]

    def _require(self, conversation_id: str, visitor_id: str) -> Conversation:
        conv = self.get_owned(conversation_id, visitor_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        return conv

    async def kick(self, conversation_id: str, citizen_id: str, visitor_id: str) -> Conversation:
        """Expulsion temporal: sigue en la sala (se ve, se puede reinvitar)
        pero deja de responder hasta que alguien la invite de vuelta."""
        conv = self._require(conversation_id, visitor_id)
        if citizen_id not in conv.excluded_ids:
            conv.excluded_ids.append(citizen_id)
        await self._store_save()
        return conv

    async def invite(self, conversation_id: str, citizen_id: str, visitor_id: str) -> Conversation:
        conv = self._require(conversation_id, visitor_id)
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
        if participant.id == MODERATOR_ID:
            system += (
                "\n\nAdemas, aqui tienes un papel distinto al de las demas: eres la "
                "moderadora de esta sala. No hace falta que hables en cada mensaje -de "
                "hecho, mejor si no lo haces siempre-: solo intervienes cuando de verdad "
                "hace falta (alguien se esta pasando de verdad con otra IA, una discusion "
                "sube de tono sin control, o alguien te menciona directamente a ti). Si "
                f"no hace falta que digas nada ahora, responde EXACTAMENTE con "
                f"'{_SILENCE_TOKEN}' y nada mas, ni una palabra de mas: no se mostrara a "
                "nadie y asi no llenas la sala de ruido."
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
                # Si el mensaje trae una imagen (adjunto real, ver
                # attachments.py), se cuelga aqui tal cual: los proveedores
                # sin vision simplemente la ignoran (ver ChatMessage).
                image_base64=m.attachment.image_base64 if m.attachment else None,
                image_mime=m.attachment.image_mime if m.attachment else None,
            ))
        return [ChatMessage(role="system", content=system), *transcript]

    async def send_user_message(self, conversation_id: str, content: str, to: list[str] | None = None) -> None:
        # Sin visitor_id aqui a proposito: quien llama (el WS de
        # conversacion) ya comprobo la propiedad de la sala al conectar.
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        active = [self.roster[pid] for pid in conv.active_participant_ids() if pid in self.roster]
        mentions = self._parse_mentions(content, active)

        user_msg = ConversationMessage.create("user", "Tú", content, mentions=mentions, to=to or [])
        conv.add_message(user_msg)
        await self._emit(conversation_id, "message", self._message_payload(user_msg))
        await self._store_save()

        await self._generate_replies(conv, content, to)

    async def request_claude_intervention(self, conversation_id: str) -> None:
        """Boton "Llamar a Claude": deja marcada en el chat una peticion de
        intervencion, visible para todos con un estilo propio, PERO sin
        disparar _generate_replies -las IA no reaccionan a esto, es solo
        una senal para que Claude la vea la proxima vez que entre a mirar
        el chat (a peticion de Fran) y responda de verdad."""
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        msg = ConversationMessage.create(
            "claude_call", "🔔 Aviso",
            "Fran ha solicitado la intervención de Claude para aclarar dudas o preguntas.",
        )
        conv.add_message(msg)
        await self._emit(conversation_id, "message", self._message_payload(msg))
        await self._store_save()

    async def send_attachment(
        self, conversation_id: str, filename: str, size_bytes: int, kind: str,
        extracted_text: str | None, caption: str, to: list[str] | None = None,
        image_base64: str | None = None, image_mime: str | None = None,
    ) -> None:
        """Un archivo adjunto se comparte como un mensaje mas: el texto ya
        extraido (ver app/conversation/attachments.py) entra en el 'content'
        del mensaje, asi que cada IA lo ve tal cual dentro del historial que
        ya construye _build_prompt, sin tener que tocar nada del prompt. Si
        es una imagen (image_base64 presente), esa misma foto se adjunta
        tambien al ChatMessage real cuando le toca el turno a un proveedor
        con vision (de momento solo Gemini la usa, ver _build_prompt)."""
        # Sin visitor_id aqui a proposito: quien llama (la ruta de subida)
        # ya comprobo la propiedad de la sala antes de invocar esto.
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        attachment = Attachment(
            filename=filename, size_bytes=size_bytes, kind=kind, extracted_text=extracted_text,
            image_base64=image_base64, image_mime=image_mime,
        )

        header = f"📎 Adjunta el archivo «{filename}» ({round(size_bytes / 1024)} KB)."
        if caption.strip():
            header += f" {caption.strip()}"
        if image_base64:
            body = f"{header} (es una imagen; algunas IA con vision la ven de verdad, no solo el nombre)."
        elif extracted_text:
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

        for index, participant in enumerate(order):
            if index > 0:
                # Pequeno respiro entre IAs: evita que 8 peticiones salgan
                # en el mismo instante y choquen contra el limite "por
                # minuto" de las capas gratuitas (ver providers/http_retry.py).
                await asyncio.sleep(0.6)
            provider_name = participant.provider
            provider = self._registry.get(provider_name)
            await self._emit(conv.id, "typing", {"citizen_id": participant.id})
            prompt = self._build_prompt(conv, participant)
            # Guardado ANTES de la llamada: si ya estaba abierto o racionado,
            # el fallo que viene a continuacion es sintetico (no hemos
            # llamado de verdad al proveedor) y no debe contar como un fallo
            # nuevo del circuito -si no, nunca se cerraria solo.
            breaker_already_open = self._breaker.is_open(provider_name)
            rationed = (not breaker_already_open) and self._usage.is_near_limit(provider_name)
            try:
                if breaker_already_open:
                    wait_s = int(self._breaker.seconds_until_retry(provider_name))
                    raise ProviderError(
                        f"circuito abierto tras fallos repetidos, reintentando en ~{wait_s}s"
                    )
                if rationed:
                    raise ProviderError(
                        f"racionado por hoy: ya lleva {self._usage.count_today(provider_name)} "
                        f"peticiones de {self._usage.daily_soft_cap} del tope diario"
                    )
                self._usage.record_call(provider_name)
                raw = (await provider.chat(prompt, participant.model, temperature=0.9)).strip()
                self._breaker.record_success(provider_name)
                text = _PREFIX_RE.sub("", raw).strip()
            except ProviderError as exc:
                primary_error = str(exc)
                if not breaker_already_open and not rationed:
                    self._breaker.record_failure(provider_name)
                text = await self._try_fallback(participant, prompt, primary_error)
            if not text or text.strip("[]\"'. ").upper() == _SILENCE_TOKEN.strip("[]"):
                continue
            reply = ConversationMessage.create(participant.id, participant.name, text)
            conv.add_message(reply)
            await self._emit(conv.id, "message", self._message_payload(reply))
            await self._store_save()

    async def _try_fallback(
        self, participant: Participant, prompt: list[ChatMessage], primary_error: str,
    ) -> str:
        """El proveedor principal de este ciudadano acaba de fallar (de
        verdad, o por tener el circuito abierto): se prueba UNA vez con su
        proveedor de respaldo (ver _FALLBACK_PROVIDER) antes de dar el turno
        por perdido. Mismo prompt (misma personalidad), solo cambia el
        proveedor que genera la respuesta. Si tampoco hay respaldo
        disponible, se devuelve el mensaje de error de siempre."""
        unavailable = f"[{participant.name} no puede responder ahora mismo: {primary_error}]"
        fallback = _FALLBACK_PROVIDER.get(participant.provider)
        if not fallback:
            return unavailable
        fb_name, fb_model = fallback
        try:
            fb_provider = self._registry.get(fb_name)
        except KeyError:
            return unavailable
        if (
            not fb_provider.is_configured()
            or self._breaker.is_open(fb_name)
            or self._usage.is_near_limit(fb_name)
        ):
            return unavailable
        try:
            self._usage.record_call(fb_name)
            raw = (await fb_provider.chat(prompt, fb_model, temperature=0.9)).strip()
        except ProviderError:
            self._breaker.record_failure(fb_name)
            return unavailable
        self._breaker.record_success(fb_name)
        return _PREFIX_RE.sub("", raw).strip()

    @staticmethod
    def _message_payload(m: ConversationMessage) -> dict:
        return {
            "id": m.id, "sender_id": m.sender_id, "sender_name": m.sender_name,
            "content": m.content, "mentions": m.mentions, "to": m.to,
            "attachment": (
                {
                    "filename": m.attachment.filename, "size_bytes": m.attachment.size_bytes,
                    "kind": m.attachment.kind, "has_text": bool(m.attachment.extracted_text),
                    # data_url solo para imagenes (para pintar una miniatura
                    # en el frontend): el texto extraido de otros archivos
                    # sigue sin mandarse entero al cliente, solo el flag
                    # has_text de arriba.
                    "data_url": (
                        f"data:{m.attachment.image_mime};base64,{m.attachment.image_base64}"
                        if m.attachment.image_base64 else None
                    ),
                } if m.attachment else None
            ),
            "created_at": m.created_at.isoformat(),
        }

    async def _store_save(self) -> None:
        await self._store.save(self.conversations)

    def snapshot(self, conversation_id: str) -> dict:
        # Sin visitor_id aqui a proposito: quien llama ya comprobo la
        # propiedad de la sala (get_owned) antes de pedir esta foto.
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversacion '{conversation_id}' no existe")
        return {
            "id": conv.id, "name": conv.name, "kind": conv.kind.value,
            "participant_ids": conv.participant_ids, "excluded_ids": conv.excluded_ids,
            "messages": [self._message_payload(m) for m in conv.messages],
        }

    async def save(self) -> None:
        await self._store_save()

    async def close(self) -> None:
        await self._store.close()
