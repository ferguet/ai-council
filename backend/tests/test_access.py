"""
Puerta de entrada (clave compartida) + separacion de visitantes.

Cubre lo esencial: sin ACCESS_CODE configurada la puerta esta abierta;
con ella configurada, solo la clave correcta genera un token valido, y ese
token no se puede falsificar (ni copiando la firma de otro visitor_id, ni
inventando uno desde cero).
"""
from __future__ import annotations

from app.core import access as access_module


class _FakeSettings:
    def __init__(self, access_code: str | None) -> None:
        self.access_code = access_code


def test_gate_open_when_no_access_code(monkeypatch) -> None:
    monkeypatch.setattr(access_module, "get_settings", lambda: _FakeSettings(None))
    assert access_module.check_code("cualquier-cosa") is True
    assert access_module.gate_enabled() is False
    # sin puerta, el token es el propio visitor_id, sin firma
    vid = access_module.new_visitor_id()
    token = access_module.issue_token(vid)
    assert token == vid
    assert access_module.verify_token(token) == vid


def test_gate_closed_requires_correct_code(monkeypatch) -> None:
    monkeypatch.setattr(access_module, "get_settings", lambda: _FakeSettings("clave-secreta"))
    assert access_module.gate_enabled() is True
    assert access_module.check_code("clave-secreta") is True
    assert access_module.check_code("  clave-secreta  ") is True  # espacios de mas, tolerado
    assert access_module.check_code("otra-cosa") is False
    assert access_module.check_code("") is False


def test_issued_token_roundtrips_and_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setattr(access_module, "get_settings", lambda: _FakeSettings("clave-secreta"))
    vid = access_module.new_visitor_id()
    token = access_module.issue_token(vid)

    assert access_module.verify_token(token) == vid
    assert access_module.verify_token(None) is None
    assert access_module.verify_token("basura-sin-punto") is None

    # cambiar el visitor_id pero no la firma no cuela
    other_vid = access_module.new_visitor_id()
    _, sig = token.rsplit(".", 1)
    forged = f"{other_vid}.{sig}"
    assert access_module.verify_token(forged) is None


def test_token_from_one_code_invalid_after_code_rotation(monkeypatch) -> None:
    """Si Fran cambia la clave (p.ej. porque se filtro a quien no debia),
    todos los tokens repartidos con la clave anterior dejan de valer."""
    monkeypatch.setattr(access_module, "get_settings", lambda: _FakeSettings("clave-vieja"))
    vid = access_module.new_visitor_id()
    token = access_module.issue_token(vid)
    assert access_module.verify_token(token) == vid

    monkeypatch.setattr(access_module, "get_settings", lambda: _FakeSettings("clave-nueva"))
    assert access_module.verify_token(token) is None
