"""
Busqueda web real para las IA del Chat Grupal que la tienen habilitada
(Gemini y Kimi, ver _SEARCH_ENABLED_CITIZENS en conversation/engine.py).

Motivado por un caso real: el 25/07 la ciudadana "Nvidia" afirmo en el chat
tener correo y haber contactado con gente por LinkedIn/Twitter, algo
imposible -se lo invento en vez de decir que no sabia. Esto le da a algunas
IA una via real para consultar un dato en vez de rellenar el hueco con una
respuesta que suena bien pero es falsa.
"""
from __future__ import annotations

import pytest

from app.conversation.engine import ConversationEngine
from app.domain.conversation_models import Participant
from app.providers.base import AIProvider, ChatMessage, ProviderError
from app.tools.web_search import WebSearchError


class _FakeBus:
    async def publish(self, event) -> None:
        pass


class _FakeStore:
    async def save(self, conversations) -> None:
        pass

    async def close(self) -> None:
        pass


class _ScriptedProvider(AIProvider):
    """Devuelve las respuestas en el orden dado, una por cada llamada real
    -asi se puede simular "primero pide buscar, luego responde de verdad"
    sin depender de un proveedor real."""

    def __init__(self, name: str, responses: list[str]) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def chat(self, messages: list[ChatMessage], model: str, temperature: float = 0.7) -> str:
        self.calls += 1
        if not self._responses:
            raise ProviderError("sin mas respuestas guionizadas para este test")
        return self._responses.pop(0)

    async def stream_chat(self, messages, model, temperature=0.7):
        raise ProviderError("no usado en este test")
        yield ""  # pragma: no cover


class _FakeSearch:
    def __init__(self, configured: bool = True, result: str = "Resumen: dato real.", fail: bool = False) -> None:
        self._configured = configured
        self._result = result
        self._fail = fail
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        return self._configured

    async def search(self, query: str) -> str:
        self.queries.append(query)
        if self._fail:
            raise WebSearchError("fallo simulado")
        return self._result


class _NamedRegistry:
    def __init__(self, providers: dict[str, AIProvider]) -> None:
        self._providers = providers

    def get(self, name: str) -> AIProvider:
        return self._providers[name]


def _roster() -> dict[str, Participant]:
    return {
        "gemini": Participant(
            id="gemini", name="Gemini", provider="gemini", model="gemini-3.6-flash",
            system_prompt="eres gemini", avatar="G", color="#fff",
        ),
        "mistral": Participant(
            id="mistral", name="Mistral", provider="mistral", model="mistral-small-latest",
            system_prompt="eres mistral", avatar="M", color="#fff",
        ),
    }


def _engine(registry: _NamedRegistry, web_search) -> ConversationEngine:
    return ConversationEngine(
        conversations={}, roster=_roster(), registry=registry,
        event_bus=_FakeBus(), store=_FakeStore(), web_search=web_search,
    )


@pytest.mark.asyncio
async def test_search_enabled_citizen_gets_real_result_and_answers_with_it() -> None:
    gemini = _ScriptedProvider("gemini", responses=[
        "[BUSCAR: capital de Islandia]",
        "Es Reikiavik, lo acabo de comprobar.",
    ])
    search = _FakeSearch(result="Resumen: Reikiavik es la capital de Islandia.")
    eng = _engine(_NamedRegistry({"gemini": gemini}), web_search=search)
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "gemini, cual es la capital de islandia?", to=["gemini"])

    replies = [m for m in conv.messages if m.sender_id == "gemini"]
    assert len(replies) == 1
    assert replies[0].content == "Es Reikiavik, lo acabo de comprobar."
    assert search.queries == ["capital de Islandia"]
    assert gemini.calls == 2  # peticion de busqueda + respuesta real


@pytest.mark.asyncio
async def test_search_failure_does_not_break_the_turn() -> None:
    gemini = _ScriptedProvider("gemini", responses=["[BUSCAR: dato que no existe]"])
    search = _FakeSearch(fail=True)
    eng = _engine(_NamedRegistry({"gemini": gemini}), web_search=search)
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "gemini, busca algo raro", to=["gemini"])

    replies = [m for m in conv.messages if m.sender_id == "gemini"]
    assert len(replies) == 1
    assert "no he podido" in replies[0].content
    assert gemini.calls == 1  # no llega a la segunda llamada: la busqueda fallo antes


@pytest.mark.asyncio
async def test_citizen_without_search_enabled_ignores_the_token() -> None:
    mistral = _ScriptedProvider("mistral", responses=["[BUSCAR: algo]"])
    search = _FakeSearch()
    eng = _engine(_NamedRegistry({"mistral": mistral}), web_search=search)
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "mistral, dime algo", to=["mistral"])

    replies = [m for m in conv.messages if m.sender_id == "mistral"]
    assert len(replies) == 1
    assert replies[0].content == "[BUSCAR: algo]"  # se publica tal cual, no se interpreta
    assert search.queries == []
    assert mistral.calls == 1


@pytest.mark.asyncio
async def test_no_search_key_configured_disables_search_even_for_enabled_citizen() -> None:
    gemini = _ScriptedProvider("gemini", responses=["[BUSCAR: algo]"])
    search = _FakeSearch(configured=False)
    eng = _engine(_NamedRegistry({"gemini": gemini}), web_search=search)
    conv = eng.ensure_default_conversation("visitor-a")

    await eng.send_user_message(conv.id, "gemini, dime algo", to=["gemini"])

    replies = [m for m in conv.messages if m.sender_id == "gemini"]
    assert len(replies) == 1
    assert replies[0].content == "[BUSCAR: algo]"
    assert search.queries == []
    assert gemini.calls == 1
