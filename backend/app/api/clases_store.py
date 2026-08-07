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

DE UN CAJON COMPARTIDO A UNO POR PERSONA

Al principio esto lo usaba una sola persona, asi que una lista global
bastaba. En cuanto se comparte con compañeros de clase deja de bastar:
sin separacion, todos ven los apuntes de todos, y cualquiera puede
borrar los de cualquier otro sin querer.

La solucion NO es meter usuarios y contraseñas -es mas aparato del que
esto necesita, y un compañero que solo quiere grabar una clase no
deberia tener que registrarse para eso-. Cada aparato genera un
identificador propio la primera vez que se usa y lo guarda en su
navegador; ese identificador viaja en cada peticion y aqui se usa para
que cada uno vea y pueda borrar solo lo suyo.

Esto NO es seguridad de verdad -alguien que sepa lo que hace podria
falsificar el identificador de otro- pero no hace falta que lo sea: el
objetivo es que un grupo de compañeros que confian entre si no se pisen
los apuntes sin querer, no protegerse de un atacante.

Y las clases guardadas ANTES de este cambio, que no tienen dueño
asignado, quedan visibles y borrables por cualquiera -no habia forma de
saber de quien eran, asi que se tratan como del grupo entero en vez de
hacerlas desaparecer.
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

# Columna añadida despues de que la tabla ya existiera en produccion. Un
# CREATE TABLE IF NOT EXISTS no la habria traido a una tabla vieja: hace
# falta este ALTER aparte, y el DEFAULT '' es a proposito, para que las
# filas de antes de este cambio queden identificadas como "sin dueño" en
# vez de romper la insercion o quedar en NULL.
_MIGRACION_PROPIETARIO_SQL = """
ALTER TABLE clases ADD COLUMN IF NOT EXISTS propietario TEXT NOT NULL DEFAULT '';
"""

_UPSERT_SQL = """
INSERT INTO clases (fichero, texto, propietario) VALUES ($1, $2, $3)
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
            await conn.execute(_MIGRACION_PROPIETARIO_SQL)
    return _POOL


_POOL = None


def _carpeta_de(propietario: str) -> Path:
    """En disco (sin base de datos) cada dueño tiene su propia carpeta.
    Sin dueño -cadena vacia- va a una carpeta de grupo, igual que en la
    base de datos.
    """
    return _CARPETA / (_sanear_propietario(propietario) or "_grupo")


def _sanear_propietario(p: str) -> str:
    return "".join(c for c in (p or "") if c.isalnum() or c in ("-", "_"))[:64]


async def guardar(fichero: str, texto: str, propietario: str = "") -> None:
    if _hay_base_de_datos():
        pool = await _pool()
        await pool.execute(_UPSERT_SQL, fichero, texto, propietario)
    else:
        carpeta = _carpeta_de(propietario)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / fichero).write_text(texto, encoding="utf-8")


async def leer(fichero: str) -> str | None:
    """Lee por nombre de fichero, sin mirar el dueño.

    A proposito: esto lo usan los pasos DERIVADOS (resumen, guion del
    podcast...) sobre un fichero que la persona ya tiene abierto delante,
    no un listado. El filtro por dueño esta en `listar` y en `borrar`,
    que es donde de verdad importa que uno no vea ni toque lo de otro.
    """
    if _hay_base_de_datos():
        pool = await _pool()
        row = await pool.fetchrow("SELECT texto FROM clases WHERE fichero = $1", fichero)
        return row["texto"] if row else None
    if _CARPETA.exists():
        for ruta in _CARPETA.glob("*/" + fichero):
            return ruta.read_text(encoding="utf-8")
    return None


async def _rescatar_del_disco(pool) -> None:
    """
    RESCATE DE LAS CLASES QUE SE QUEDARON EN EL DISCO.

    Al pasar de guardar en disco a guardar en base de datos, se me olvido
    lo mas obvio: lo que YA estaba guardado en el disco seguia ahi, pero
    el listado pasó a mirar solo la base de datos. Resultado: las clases
    de antes desaparecieron de la vista de golpe, sin avisar, como si se
    hubieran borrado.

    Mudarse de casa y dejarse las cosas dentro es un fallo tan tonto como
    grave. Esto las trae al sitio nuevo la primera vez que se mira.

    Estos ficheros son de antes de que existiera el concepto de dueño, asi
    que entran como "sin dueño": visibles y borrables por el grupo entero,
    igual que cualquier otra fila anterior a este cambio.
    """
    if not _CARPETA.exists():
        return
    for f in _CARPETA.glob("**/*.txt"):
        try:
            ya = await pool.fetchrow("SELECT 1 FROM clases WHERE fichero = $1", f.name)
            if ya is None:
                await pool.execute(
                    _UPSERT_SQL, f.name, f.read_text(encoding="utf-8"), ""
                )
        except Exception:
            pass


async def listar(propietario: str = "") -> list[str]:
    """Lo tuyo, mas lo que quedo sin dueño de antes de este cambio."""
    if _hay_base_de_datos():
        pool = await _pool()
        await _rescatar_del_disco(pool)
        filas = await pool.fetch(
            "SELECT fichero FROM clases WHERE (propietario = $1 OR propietario = '') "
            "ORDER BY fichero DESC",
            propietario,
        )
        return [f["fichero"] for f in filas]
    if not _CARPETA.exists():
        return []
    propias = list(_carpeta_de(propietario).glob("*.txt")) if propietario else []
    grupo = list((_CARPETA / "_grupo").glob("*.txt"))
    return [f.name for f in sorted(set(propias) | set(grupo),
                                    key=lambda p: p.name, reverse=True)]


async def borrar(fichero: str, propietario: str = "") -> bool:
    """
    Borra una clase, solo si es tuya o si quedo sin dueño. Devuelve si
    de verdad se ha borrado algo.

    Borra tambien del disco si estuviera ahi: si no, una clase rescatada
    del disco viejo volveria a aparecer en el siguiente listado, porque el
    rescate la copiaria otra vez. Un borrado que no borra del todo es peor
    que no tener borrado.
    """
    borrado = False
    if _hay_base_de_datos():
        pool = await _pool()
        r = await pool.execute(
            "DELETE FROM clases WHERE fichero = $1 AND (propietario = $2 OR propietario = '')",
            fichero, propietario,
        )
        borrado = r.endswith("1")
    # En disco se mira SOLO en la carpeta propia y en la de grupo -nunca
    # en la de otro dueño, aunque por casualidad se supiera el nombre
    # exacto de su fichero. Un glob abierto a "*/" + fichero habria
    # encontrado y borrado el de cualquiera.
    for carpeta in {_carpeta_de(propietario), _CARPETA / "_grupo"}:
        ruta = carpeta / fichero
        if ruta.is_file():
            ruta.unlink()
            borrado = True
    return borrado


async def donde_se_guarda() -> str:
    """
    Para poder decirlo en pantalla en vez de que la persona lo suponga.
    Saber si tus clases estan a salvo o no no deberia ser un misterio.
    """
    return "base de datos (permanente)" if _hay_base_de_datos() else "disco del servidor"
