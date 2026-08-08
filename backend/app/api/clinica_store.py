"""
DONDE SE GUARDAN LOS CASOS Y LAS FICHAS EXPLICADAS.

Mismo planteamiento que clases_store, y por el mismo motivo: en el plan
gratuito de Render el disco NO es persistente, asi que si hay DATABASE_URL
se usa Postgres y si no, disco -que en un ordenador propio si aguanta-.

Aqui se guardan dos cosas distintas en la misma tabla, separadas por `tipo`:

  caso   Un caso que el alumno ha montado y quiere recuperar. Es SUYO:
         lleva propietario y solo lo ve quien lo creo.

  ficha  La parte explicada de una patologia -el por que de la clinica, por
         que se pide cada prueba, que esperamos ver...-. Se genera con IA
         UNA VEZ y se guarda para siempre. No tiene dueño: es igual para
         todo el mundo.

Lo segundo es lo que hace que la app no gaste casi nada. Cuarenta patologias
son cuarenta llamadas en toda la vida de la app, no cuarenta por sesion.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings

_CARPETA = Path("data/clinica")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS clinica (
    clave TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    texto TEXT NOT NULL,
    propietario TEXT NOT NULL DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_UPSERT_SQL = """
INSERT INTO clinica (clave, tipo, texto, propietario) VALUES ($1, $2, $3, $4)
ON CONFLICT (clave) DO UPDATE SET texto = EXCLUDED.texto;
"""

_POOL = None


def _hay_base_de_datos() -> str | None:
    return get_settings().database_url


async def _pool():
    import asyncpg
    global _POOL
    if _POOL is None:
        _POOL = await asyncpg.create_pool(_hay_base_de_datos(), min_size=1, max_size=3)
        async with _POOL.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
    return _POOL


def _sanear(t: str) -> str:
    return "".join(c for c in (t or "") if c.isalnum() or c in ("-", "_"))[:80]


def _clave(tipo: str, nombre: str, propietario: str = "") -> str:
    """
    La clave lleva el dueño dentro a proposito.

    Sin eso, dos alumnos que llamen "cefalea" a su caso se pisarian el uno al
    otro: el segundo en guardar borraria el del primero sin avisar. Meter el
    dueño en la clave hace que eso sea imposible por construccion, en vez de
    depender de acordarse de filtrar bien en cada consulta.
    """
    # Fichas y mecanismos son iguales para todo el mundo: no llevan dueño.
    if tipo in ("ficha", "mecanismos"):
        return f"{tipo}:{_sanear(nombre)}"
    return f"caso:{_sanear(propietario)}:{_sanear(nombre)}"


async def guardar(tipo: str, nombre: str, datos: dict, propietario: str = "") -> None:
    clave = _clave(tipo, nombre, propietario)
    texto = json.dumps(datos, ensure_ascii=False)
    if _hay_base_de_datos():
        pool = await _pool()
        await pool.execute(_UPSERT_SQL, clave, tipo, texto, propietario)
    else:
        _CARPETA.mkdir(parents=True, exist_ok=True)
        (_CARPETA / f"{clave.replace(':', '__')}.json").write_text(texto, encoding="utf-8")


async def leer(tipo: str, nombre: str, propietario: str = "") -> dict | None:
    clave = _clave(tipo, nombre, propietario)
    if _hay_base_de_datos():
        pool = await _pool()
        fila = await pool.fetchrow("SELECT texto FROM clinica WHERE clave = $1", clave)
        if not fila:
            return None
        try:
            return json.loads(fila["texto"])
        except json.JSONDecodeError:
            return None
    ruta = _CARPETA / f"{clave.replace(':', '__')}.json"
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


async def listar_casos(propietario: str = "") -> list[dict]:
    """Solo los casos de quien pregunta. Aqui no hay clausula de grupo: un
    caso clinico montado por otro no aporta nada y solo estorba."""
    if _hay_base_de_datos():
        pool = await _pool()
        filas = await pool.fetch(
            "SELECT clave, texto, creado_en FROM clinica "
            "WHERE tipo = 'caso' AND propietario = $1 ORDER BY creado_en DESC",
            propietario,
        )
        salida = []
        for f in filas:
            try:
                d = json.loads(f["texto"])
            except json.JSONDecodeError:
                continue
            salida.append({"nombre": d.get("nombre", ""), "datos": len(d.get("datos", []))})
        return salida
    if not _CARPETA.exists():
        return []
    prefijo = f"caso__{_sanear(propietario)}__"
    salida = []
    for ruta in sorted(_CARPETA.glob(f"{prefijo}*.json"), reverse=True):
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        salida.append({"nombre": d.get("nombre", ""), "datos": len(d.get("datos", []))})
    return salida


async def borrar_caso(nombre: str, propietario: str = "") -> bool:
    clave = _clave("caso", nombre, propietario)
    borrado = False
    if _hay_base_de_datos():
        pool = await _pool()
        r = await pool.execute("DELETE FROM clinica WHERE clave = $1 AND tipo = 'caso'", clave)
        borrado = r.endswith("1")
    ruta = _CARPETA / f"{clave.replace(':', '__')}.json"
    if ruta.is_file():
        ruta.unlink()
        borrado = True
    return borrado
