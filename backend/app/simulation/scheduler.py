"""
Bucle de fondo que hace avanzar la Ciudad Virtual sola, exista o no un
cliente conectado. Se arranca una vez en el evento startup de FastAPI
(ver app/main.py) y sigue corriendo mientras el proceso este vivo.
"""
from __future__ import annotations

import asyncio
import logging

from app.simulation.engine import SimulationEngine

logger = logging.getLogger("city.scheduler")


class SimulationScheduler:
    def __init__(self, engine: SimulationEngine, tick_seconds: int = 60) -> None:
        self._engine = engine
        self._tick_seconds = tick_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._tick_seconds)
                await self._engine.tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error en el tick de simulacion; se reintenta en el siguiente ciclo.")
