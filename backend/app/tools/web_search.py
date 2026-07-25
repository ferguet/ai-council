"""
Busqueda web real para las IA del Chat Grupal que la tienen habilitada (ver
_SEARCH_ENABLED_CITIZENS en conversation/engine.py).

Sin esto, las IA no tienen forma de saber nada del mundo real fuera de lo
que se ha dicho en el chat -y como se vio el 25/07, cuando no saben algo a
veces se lo inventan en vez de decir "no lo se". Esto les da una via real
para buscar un dato concreto en vez de rellenar el hueco con una respuesta
que suena bien pero es falsa.

Usa la API de Tavily (pensada para dar resultados ya resumidos a una IA, no
una pagina de resultados para un humano). Cuenta gratis en
https://tavily.com, sin tarjeta.
"""
from __future__ import annotations

import httpx

from app.providers.http_retry import post_with_retry

_URL = "https://api.tavily.com/search"
_MAX_RESULTS = 4
_TIMEOUT = 20.0
_SNIPPET_CHARS = 400


class WebSearchError(RuntimeError):
    """Fallo al buscar en internet (sin clave, sin red, o la propia API)."""


class WebSearchClient:
    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str) -> str:
        """Devuelve un resumen en texto plano (respuesta + titulo/extracto
        de cada resultado), listo para pegar en el prompt de una IA -no la
        respuesta cruda de la API, que trae mucho ruido que no hace falta."""
        if not self._api_key:
            raise WebSearchError("TAVILY_API_KEY no configurada")
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": _MAX_RESULTS,
            "include_answer": True,
        }
        try:
            resp = await post_with_retry(
                _URL, headers={"Content-Type": "application/json"}, json=payload,
                timeout=_TIMEOUT, max_retries=1,
            )
        except httpx.HTTPError as exc:
            raise WebSearchError(f"error de red buscando '{query}': {exc}") from exc
        if resp.status_code != 200:
            raise WebSearchError(f"Tavily error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        parts = []
        answer = data.get("answer")
        if answer:
            parts.append(f"Resumen: {answer}")
        for r in data.get("results", [])[:_MAX_RESULTS]:
            title = r.get("title", "")
            content = (r.get("content") or "")[:_SNIPPET_CHARS]
            parts.append(f"- {title}: {content}")
        text = "\n".join(parts).strip()
        if not text:
            raise WebSearchError(f"sin resultados para '{query}'")
        return text
