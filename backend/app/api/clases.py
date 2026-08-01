"""
CLASES: transcribir audio de una clase grabada con el movil.

Primer paso del proyecto de apuntes de clase, deliberadamente pequeno: solo
grabar y transcribir. Nada de entonacion, nada de examenes del MIR, nada de
diapositivas todavia -eso viene despues, en capas, igual que se hizo con
Cuidame.

Usa Groq para transcribir (modelo Whisper alojado por ellos) en vez de un
servicio nuevo, porque la clave GROQ_API_KEY ya esta configurada en este
mismo backend para el ciudadano "groq" de la Ciudad. Ni hay que crear cuenta
nueva ni gestionar una clave mas.

SIN DATOS DE PACIENTES: esto es para clases y estudio. El modo de practicas
hospitalarias, si se hace, necesita su propio filtro de anonimizado antes de
guardar nada, y no esta implementado aqui.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings

router = APIRouter(prefix="/clases", tags=["clases"])

_GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# whisper-large-v3-turbo: la version rapida y barata de Whisper en Groq.
# Suficiente para transcribir voz de una clase; no hace falta la version
# grande para este primer paso.
_MODELO = "whisper-large-v3-turbo"

# Donde se guardan las transcripciones, junto al resto de datos persistentes
# de esta app (igual que city_state.json y conversations.json).
_CARPETA = Path("data/clases")


@router.post("/transcribir")
async def transcribir(audio: UploadFile = File(...), asignatura: str = "sin_asignatura"):
    """
    Recibe un fichero de audio, lo manda a Groq/Whisper, y guarda el texto
    resultante en un fichero de texto con la fecha. Devuelve el texto para
    que la app del movil lo enseñe al momento.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(500, "GROQ_API_KEY no configurada en el servidor")

    contenido = await audio.read()
    if not contenido:
        raise HTTPException(400, "El audio ha llegado vacío")

    # Groq cobra/limita por tamaño de fichero; un audio de mas de una hora en
    # buena calidad puede pasar de 25 MB, que es el limite de su API. Se
    # avisa aqui en vez de dejar que Groq de un error confuso.
    if len(contenido) > 25 * 1024 * 1024:
        raise HTTPException(
            413,
            "El audio pesa más de 25 MB. Para clases muy largas, hay que "
            "partirlo en trozos antes de mandarlo (pendiente de implementar "
            "en el móvil)."
        )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                _GROQ_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": (audio.filename or "clase.m4a", contenido, audio.content_type)},
                data={"model": _MODELO, "response_format": "text"},
            )
    except httpx.RequestError as e:
        raise HTTPException(502, f"No se pudo contactar con Groq: {e}")

    if resp.status_code != 200:
        raise HTTPException(502, f"Groq devolvió un error: {resp.text[:300]}")

    texto = resp.text

    ahora = datetime.now(timezone.utc)
    _CARPETA.mkdir(parents=True, exist_ok=True)
    nombre = f"{ahora.strftime('%Y-%m-%d_%H%M')}_{_sanear(asignatura)}.txt"
    ruta = _CARPETA / nombre
    ruta.write_text(texto, encoding="utf-8")

    return {
        "texto": texto,
        "fichero": nombre,
        "asignatura": asignatura,
        "fecha": ahora.isoformat(),
    }


@router.get("/listar")
async def listar():
    """Las clases ya transcritas, mas recientes primero."""
    if not _CARPETA.exists():
        return {"clases": []}
    ficheros = sorted(_CARPETA.glob("*.txt"), reverse=True)
    return {"clases": [f.name for f in ficheros]}


@router.get("/leer/{fichero}")
async def leer(fichero: str):
    """El texto de una clase concreta, para volver a consultarlo."""
    ruta = _CARPETA / fichero
    # Evitar salir de la carpeta con "../algo": solo nombres de fichero
    # sueltos, nunca rutas.
    if "/" in fichero or "\\" in fichero or not ruta.is_file():
        raise HTTPException(404, "No existe esa clase")
    return {"texto": ruta.read_text(encoding="utf-8")}


def _sanear(texto: str) -> str:
    permitido = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(c if c in permitido else "_" for c in texto)[:40] or "sin_asignatura"
