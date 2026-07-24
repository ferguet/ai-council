"""
Persistencia alternativa de las conversaciones en Postgres (misma logica
que app/simulation/persistence_pg.py, tabla distinta). Se usa cuando hay un
DATABASE_URL configurado, para que el chat grupal sobreviva a que Render
duerma o reinicie el servicio.
"""
from __future__ import annotations

import json

import asyncpg

from app.conversation.persistence import conversations_from_dict, conversations_to_dict
from app.domain.conversation_models import Conversation

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_conversations (
    id INTEGER PRIMARY KEY DEFAULT 1,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (id = 1)
);
"""

_UPSERT_SQL = """
INSERT INTO chat_conversations (id, data, updated_at) VALUES (1, $1::jsonb, now())
ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now();
"""


class PostgresConversationStore:
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
        row = await pool.fetchrow("SELECT 1 FROM chat_conversations WHERE id = 1")
        return row is not None

    async def load(self) -> dict[str, Conversation]:
        pool = await self._get_pool()
        row = await pool.fetchrow("SELECT data FROM chat_conversations WHERE id = 1")
        raw = row["data"]
        data = json.loads(raw) if isinstance(raw, str) else raw
        return conversations_from_dict(data)

    async def save(self, conversations: dict[str, Conversation]) -> None:
        pool = await self._get_pool()
        payload = json.dumps(conversations_to_dict(conversations), ensure_ascii=False)
        await pool.execute(_UPSERT_SQL, payload)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
