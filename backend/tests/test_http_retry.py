"""
Reintento con backoff para las llamadas a los proveedores de IA
(app/providers/http_retry.py). Esto es lo que ataca directamente el
"problema de los tokens": los 429 de limite de peticiones por minuto de las
capas gratuitas se resuelven solos con un par de reintentos cortos, sin que
el usuario llegue a ver el aviso de "sin cuota ahora mismo".
"""
from __future__ import annotations

import httpx
import pytest

from app.providers.http_retry import _wait_seconds, post_with_retry


def _make_client_and_counter(statuses: list[int], headers: list[dict] | None = None):
    """Un transporte falso que devuelve, en orden, un status distinto en
    cada llamada (y se queda en el ultimo si se le pide mas de las que hay)."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = min(calls["count"], len(statuses) - 1)
        calls["count"] += 1
        extra = (headers[i] if headers else {}) or {}
        return httpx.Response(statuses[i], json={"ok": statuses[i] == 200}, headers=extra)

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_post_with_retry_returns_first_success_without_waiting(monkeypatch):
    transport, calls = _make_client_and_counter([200])
    _patch_client(monkeypatch, transport)

    resp = await post_with_retry("https://x.test/chat", headers={}, json={}, max_retries=2)

    assert resp.status_code == 200
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_post_with_retry_retries_on_429_then_succeeds(monkeypatch):
    transport, calls = _make_client_and_counter([429, 200])
    _patch_client(monkeypatch, transport)
    slept = []
    monkeypatch.setattr("app.providers.http_retry.asyncio.sleep", _fake_sleep(slept))

    resp = await post_with_retry("https://x.test/chat", headers={}, json={}, max_retries=2)

    assert resp.status_code == 200
    assert calls["count"] == 2
    assert len(slept) == 1  # espero una vez, antes del segundo intento


@pytest.mark.asyncio
async def test_post_with_retry_gives_up_after_max_retries(monkeypatch):
    transport, calls = _make_client_and_counter([429, 429, 429])
    _patch_client(monkeypatch, transport)
    monkeypatch.setattr("app.providers.http_retry.asyncio.sleep", _fake_sleep([]))

    resp = await post_with_retry("https://x.test/chat", headers={}, json={}, max_retries=2)

    assert resp.status_code == 429  # se rinde y devuelve el ultimo fallo, no lo esconde
    assert calls["count"] == 3  # 1 intento + 2 reintentos, ni uno mas


@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_non_retryable_status(monkeypatch):
    """Una key invalida (401) no se arregla reintentando: hay que fallar a
    la primera para no gastar mas peticiones contra el mismo limite."""
    transport, calls = _make_client_and_counter([401])
    _patch_client(monkeypatch, transport)
    monkeypatch.setattr("app.providers.http_retry.asyncio.sleep", _fake_sleep([]))

    resp = await post_with_retry("https://x.test/chat", headers={}, json={}, max_retries=2)

    assert resp.status_code == 401
    assert calls["count"] == 1


def test_wait_seconds_respects_retry_after_header():
    resp = httpx.Response(429, headers={"Retry-After": "3"})
    assert _wait_seconds(resp, attempt=0) == 3.0


def test_wait_seconds_caps_retry_after_at_max():
    resp = httpx.Response(429, headers={"Retry-After": "999"})
    assert _wait_seconds(resp, attempt=0) == 20.0


def test_wait_seconds_falls_back_to_backoff_without_header():
    resp = httpx.Response(429)
    wait = _wait_seconds(resp, attempt=1)
    assert 2.0 <= wait <= 2.5  # 2**1 + jitter [0, 0.5)


def _fake_sleep(recorded: list):
    async def _sleep(seconds: float) -> None:
        recorded.append(seconds)

    return _sleep


def _patch_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """post_with_retry crea su propio httpx.AsyncClient(timeout=...) por
    dentro; le inyectamos el transporte falso interceptando el constructor
    para no tener que tocar la firma de la funcion solo por testear."""
    real_client_cls = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("app.providers.http_retry.httpx.AsyncClient", _client_factory)
