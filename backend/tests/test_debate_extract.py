"""
Adjuntar un documento al debate: /debate/extract reutiliza el mismo
extractor de texto que los adjuntos del Chat Grupal, pero sin guardar nada
ni tocar ninguna sesion -- solo devuelve el texto para que el frontend lo
anada al tema antes de arrancar el WebSocket.

Puerta de acceso abierta en estos tests (sin ACCESS_CODE en el entorno de
test), asi que require_visitor no exige token de verdad.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
_HEADERS = {"X-Visitor-Token": "visitor-de-prueba"}  # puerta abierta en test, pero require_visitor exige algun token


def test_extract_returns_text_for_supported_file():
    files = {"file": ("notas.txt", b"contenido de prueba para el debate", "text/plain")}
    r = client.post("/debate/extract", files=files, headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "notas.txt"
    assert body["kind"] == "text"
    assert "contenido de prueba" in body["extracted_text"]


def test_extract_rejects_unsupported_type():
    files = {"file": ("cancion.mp3", b"\x00\x01\x02", "audio/mpeg")}
    r = client.post("/debate/extract", files=files, headers=_HEADERS)
    assert r.status_code == 422


def test_extract_rejects_oversized_file():
    big = b"x" * (8 * 1024 * 1024 + 1)
    files = {"file": ("grande.txt", big, "text/plain")}
    r = client.post("/debate/extract", files=files, headers=_HEADERS)
    assert r.status_code == 413


def test_extract_requires_visitor_token():
    files = {"file": ("notas.txt", b"algo", "text/plain")}
    r = client.post("/debate/extract", files=files)
    assert r.status_code == 401
