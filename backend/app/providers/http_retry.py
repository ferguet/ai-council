"""
Reintento con backoff para las llamadas HTTP a los proveedores de IA.

El "problema de los tokens" que se ve en produccion (mensajes de "sin cuota
ahora mismo") casi siempre es un limite de peticiones POR MINUTO de la capa
gratuita (429 Too Many Requests), no que la cuota del dia entero este
agotada: con 8-11 ciudadanos hablando y el Chat Grupal respondiendo con
todos a la vez, es facil chocar un instante contra ese limite aunque sobre
cuota de sobra. Un par de reintentos cortos, esperando lo que pida el propio
proveedor (header Retry-After) o un backoff exponencial si no lo manda,
resuelve la inmensa mayoria de esos casos sin que el usuario vea ningun
error ni se pierda una respuesta.

Los errores que no son transitorios (401 de key invalida, 400 de payload
mal formado, etc.) se devuelven a la primera: reintentarlos no arregla nada
y solo gasta mas peticiones contra el mismo limite.
"""
from __future__ import annotations

import asyncio
import random

import httpx

# 429: limite de peticiones. 500/502/503/504: caida puntual del proveedor,
# tambien merece la pena reintentar un par de veces.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Tope maximo de espera entre reintentos: si un proveedor pide un
# Retry-After absurdamente largo, mejor fallar rapido (y que el usuario vea
# el aviso de "sin cuota") que dejar el tick de la ciudad o el chat colgado.
_MAX_WAIT_SECONDS = 20.0


async def post_with_retry(
    url: str,
    *,
    headers: dict,
    json: dict,
    timeout: httpx.Timeout | float = 60,
    max_retries: int = 2,
) -> httpx.Response:
    """POST con hasta `max_retries` reintentos si la respuesta es un error
    transitorio. Devuelve la respuesta tal cual (exitosa o fallida) para que
    cada proveedor siga interpretando el status_code como ya hacia; quien
    llama no necesita saber que hubo reintentos."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=json)
        for attempt in range(max_retries):
            if resp.status_code not in _RETRYABLE_STATUS:
                return resp
            await asyncio.sleep(_wait_seconds(resp, attempt))
            resp = await client.post(url, headers=headers, json=json)
        return resp


def _wait_seconds(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_WAIT_SECONDS)
        except ValueError:
            pass
    # Backoff exponencial con jitter: 1-1.5s, luego 2-2.5s...
    return min((2 ** attempt) + random.uniform(0, 0.5), _MAX_WAIT_SECONDS)
