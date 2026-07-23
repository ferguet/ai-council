"""
Persistencia alternativa del WorldState en Postgres.

Se usa cuando hay un DATABASE_URL configurado (p.ej. desplegando en Render
con una base de datos gratuita de Supabase, donde el disco local del
servicio NO es persistente entre reinicios). Misma idea que persistence.py
-- todo el mundo cabe en un unico blob JSON -- pero guardado en una fila de
tabla en vez de en un fichero local.

Interfaz async a proposito (a diferencia de WorldStore, que es sincrona):
aqui cada guardado es una llamada de red, y no queremos bloquear el event
loop de FastAPI en cada tick de la simulacion.
"""
from __future__ import annotations

import json

import asyncpg

from app.domain.city_models import WorldState
from app.simulation.persistence import world_from_dict, world_to_dict

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS city_world (
    id INTEGER PRIMARY KEY DEFAULT 1,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (id = 1)
);
"""

_UPSERT_SQL = """
INSERT INTO city_world (id, data, updated_at) VALUES (1, $1::jsonb, now())
ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now();
"""


class PostgresWorldStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=3)
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
        return self._pool

    async def exists(self) -> bool:
        pool = await self._get_pool()
        row = await pool.fetchrow("SELECT 1 FROM city_world WHERE id = 1")
        return row is not None

    async def load(self) -> WorldState:
        pool = await self._get_pool()
        row = await pool.fetchrow("SELECT data FROM city_world WHERE id = 1")
        raw = row["data"]
        data = json.loads(raw) if isinstance(raw, str) else raw
        return world_from_dict(data)

    async def save(self, world: WorldState) -> None:
        pool = await self._get_pool()
        payload = json.dumps(world_to_dict(world), ensure_ascii=False)
        await pool.execute(_UPSERT_SQL, payload)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
