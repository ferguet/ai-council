"""
DONDE SE GUARDAN LAS CLASES, PARA QUE NO SE PIERDAN.

EL PROBLEMA QUE RESUELVE

Las transcripciones se estaban guardando en ficheros dentro del servidor,
y en el plan gratuito de Render el disco NO es persistente: cuando el
servicio se reinicia -y se reinicia solo, al desplegar o al despertarse
mal- ese disco se borra entero.

O sea que alguien podia grabar cinco clases, verlas en la lista tan
tranquilo, y encontrarse la lista vacia al dia siguiente sin que nadie le
hubiera avisado de nada. Es el mismo fallo silencioso que perseguimos en
Cuidame: parece que esta guardado, y no lo esta.

COMO SE RESUELVE

Igual que la Ciudad: si hay un DATABASE_URL configurado (el Postgres de
Supabase que ya existe), las clases se guardan ahi, que si sobrevive a los
reinicios. Si no lo hay -por ejemplo en local- se sigue usando el disco,
que en un ordenador propio si es permanente.

La eleccion es automatica y no hay que tocar nada: el resto del codigo
llama a las mismas funciones sin enterarse de donde acaba el texto.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings

_CARPETA = Path("data/clases")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS clases (
    fichero TEXT PRIMARY KEY,
    texto TEXT NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_UPSERT_SQL = """
INSERT INTO clases (fichero, texto) VALUES ($1, $2)
ON CONFLICT (fichero) DO UPDATE SET texto = EXCLUDED.texto;
"""


def _hay_base_de_datos() -> str | None:
    return get_settings().database_url


async def _pool():
    """Conexion perezosa: solo se crea si de verdad hay base de datos."""
    import asyncpg
    global _POOL
    if _POOL is None:
        _POOL = await asyncpg.create_pool(_hay_base_de_datos(), min_size=1, max_size=3)
        async with _POOL.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
    return _POOL


_POOL = None


async def guardar(fichero: str, texto: str) -> None:
    if _hay_base_de_datos():
        pool = await _pool()
        await pool.execute(_UPSERT_SQL, fichero, texto)
    else:
        _CARPETA.mkdir(parents=True, exist_ok=True)
        (_CARPETA / fichero).write_text(texto, encoding="utf-8")


async def leer(fichero: str) -> str | None:
    if _hay_base_de_datos():
        pool = await _pool()
        row = await pool.fetchrow("SELECT texto FROM clases WHERE fichero = $1", fichero)
        return row["texto"] if row else None
    ruta = _CARPETA / fichero
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else None


async def listar() -> list[str]:
    if _hay_base_de_datos():
        pool = await _pool()
        filas = await pool.fetch("SELECT fichero FROM clases ORDER BY fichero DESC")
        return [f["fichero"] for f in filas]
    if not _CARPETA.exists():
        return []
    return [f.name for f in sorted(_CARPETA.glob("*.txt"), reverse=True)]


async def donde_se_guarda() -> str:
    """
    Para poder decirlo en pantalla en vez de que la persona lo suponga.
    Saber si tus clases estan a salvo o no no deberia ser un misterio.
    """
    return "base de datos (permanente)" if _hay_base_de_datos() else "disco del servidor"
