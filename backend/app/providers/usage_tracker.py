"""
Racionamiento diario por proveedor en el Chat Grupal.

Lleva la cuenta de peticiones reales hechas a cada proveedor a lo largo del
dia (UTC) y, al llegar al tope diario configurado, deja de llamarlo de
verdad el resto del dia -antes de que el proveedor devuelva el 429, no
despues- dejando que el proveedor de respaldo (ver _FALLBACK_PROVIDER en
conversation/engine.py) siga respondiendo por ese ciudadano sin cortes.

No conocemos con precision el limite diario real de cada proveedor (varia
por plan, cambia sin aviso del proveedor y no es igual de publico para
todos), asi que en vez de "adivinar" un numero por proveedor se usa un tope
generico y conservador (PROVIDER_DAILY_SOFT_CAP, ver core/config.py) igual
para todos: mejor pecar de prudente y depender un poco mas del proveedor de
respaldo, que agotar la cuota real de un proveedor y quedarse sin nada el
resto del dia.

Se resetea solo: cada proveedor lleva su propia fecha (UTC) junto al
contador, asi que en cuanto cambia el dia su cuenta vuelve a cero sin que
haga falta ningun cron ni tarea de limpieza aparte.

Idea de "racionar" propuesta por Fran, inspirada en la sugerencia de
"colas/limites" que planteo la ciudadana Kimi en el Chat Grupal (24/07).
"""
from __future__ import annotations

from datetime import date, datetime, timezone


class ProviderUsageTracker:
    def __init__(self, daily_soft_cap: int = 150) -> None:
        self._daily_soft_cap = daily_soft_cap
        self._day: dict[str, date] = {}
        self._count: dict[str, int] = {}

    @staticmethod
    def _today(now: datetime | None) -> date:
        return (now or datetime.now(timezone.utc)).date()

    def _roll_if_new_day(self, name: str, today: date) -> None:
        if self._day.get(name) != today:
            self._day[name] = today
            self._count[name] = 0

    def record_call(self, name: str, *, now: datetime | None = None) -> None:
        today = self._today(now)
        self._roll_if_new_day(name, today)
        self._count[name] = self._count.get(name, 0) + 1

    def count_today(self, name: str, *, now: datetime | None = None) -> int:
        today = self._today(now)
        self._roll_if_new_day(name, today)
        return self._count.get(name, 0)

    def is_near_limit(self, name: str, *, now: datetime | None = None) -> bool:
        return self.count_today(name, now=now) >= self._daily_soft_cap

    def remaining_today(self, name: str, *, now: datetime | None = None) -> int:
        return max(0, self._daily_soft_cap - self.count_today(name, now=now))

    @property
    def daily_soft_cap(self) -> int:
        return self._daily_soft_cap
