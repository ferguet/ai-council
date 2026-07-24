"""
Circuit breaker por proveedor de IA.

Sin esto, cada ronda del Chat Grupal vuelve a intentar una llamada real
contra un proveedor que ya sabemos que esta caido (p.ej. cuota de Gemini
agotada, ver el 429 del 24/07) -- gastando el turno entero en golpear una
puerta que sigue cerrada. Tras N fallos SEGUIDOS de un mismo proveedor, se
abre el circuito unos minutos: durante ese tiempo se da por fallido sin
siquiera intentar la llamada real, y se libera turno para el proveedor de
respaldo (ver _FALLBACK_PROVIDER en conversation/engine.py).

Idea propuesta por la ciudadana "Kimi" en el propio Chat Grupal (24/07),
validada y adaptada por Claude a como esta app llama de verdad a los
proveedores (no hay "nodos" reales, solo una clave/cuota por proveedor).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 3 fallos seguidos y se abre; se mantiene abierto 3 minutos antes de dejar
# pasar un intento nuevo. Numeros deliberadamente prudentes: ni tan bajos
# que un fallo suelto (un timeout de red puntual) tumbe el proveedor entero,
# ni tan altos que se sigan quemando turnos contra una cuota agotada.
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_OPEN_SECONDS = 180.0


class ProviderCircuitBreaker:
    """Un circuito independiente por nombre de proveedor (p.ej. 'gemini2',
    'openrouter'). Sin estado global: cada instancia de ConversationEngine
    lleva la suya, igual que ya hace con el registro de proveedores."""

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        open_seconds: float = DEFAULT_OPEN_SECONDS,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._open_seconds = open_seconds
        self._failures: dict[str, int] = {}
        self._opened_until: dict[str, datetime] = {}

    def is_open(self, name: str, *, now: datetime | None = None) -> bool:
        until = self._opened_until.get(name)
        if until is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now >= until:
            # Paso el tiempo de espera: se cierra solo y se le da una
            # oportunidad nueva (con el contador de fallos a cero, para que
            # haga falta volver a fallar 3 veces seguidas antes de reabrirse).
            del self._opened_until[name]
            self._failures[name] = 0
            return False
        return True

    def record_success(self, name: str) -> None:
        self._failures[name] = 0
        self._opened_until.pop(name, None)

    def record_failure(self, name: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count >= self._failure_threshold:
            self._opened_until[name] = now + timedelta(seconds=self._open_seconds)

    def seconds_until_retry(self, name: str, *, now: datetime | None = None) -> float:
        until = self._opened_until.get(name)
        if until is None:
            return 0.0
        now = now or datetime.now(timezone.utc)
        return max(0.0, (until - now).total_seconds())
