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
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry

router = APIRouter(prefix="/clases", tags=["clases"])

# Mismo proveedor que la transcripcion (Groq), y mismo motivo: la clave ya
# esta configurada para el ciudadano "groq" de la Ciudad, sin cuenta nueva
# que crear. Es trabajo mecanico -condensar un texto largo en apuntes
# organizados-, asi que no hace falta un modelo caro para hacerlo bien.
_PROVEEDOR_RESUMEN = "groq"
_MODELO_RESUMEN = "llama-3.3-70b-versatile"

_INSTRUCCION_RESUMEN = (
    "Eres un asistente que convierte la transcripcion literal de una clase "
    "universitaria (medicina) en apuntes de estudio organizados. Sigue estas "
    "reglas:\n"
    "1. Organiza por temas o conceptos, con un titulo corto por bloque.\n"
    "2. Para cada concepto, redacta la explicacion en un parrafo claro, no "
    "solo palabras sueltas: alguien que no fue a la clase tiene que poder "
    "entenderlo.\n"
    "3. Si el profesor dice explicitamente que algo 'no entra' o 'no lo va a "
    "preguntar', escribe ese aviso en una linea aparte que empiece por "
    "'NO ENTRA:' justo debajo del concepto correspondiente.\n"
    "4. Si el profesor repite una idea varias veces o le dedica mucho "
    "tiempo, añade al final del bloque la etiqueta '(insistido)'.\n"
    "5. No inventes nada que no este en la transcripcion. Si una parte del "
    "audio no se entiende bien, dilo en vez de rellenar con suposiciones.\n"
    "6. Al final, añade un apartado 'REPASO RAPIDO' con las 3-5 ideas mas "
    "importantes de toda la clase, una linea cada una."
)


@router.post("/resumir/{fichero}")
async def resumir(fichero: str):
    """
    Coge una transcripcion ya guardada y le pide a una IA que la convierta
    en apuntes organizados. Se guarda junto al original, con el mismo
    nombre y sufijo "_resumen", para no perder ni la transcripcion literal
    ni el resumen si hay que volver a mirar el audio original de alguna
    frase concreta.
    """
    ruta = _CARPETA / fichero
    if "/" in fichero or "\\" in fichero or not ruta.is_file():
        raise HTTPException(404, "No existe esa clase")

    texto = ruta.read_text(encoding="utf-8")
    if len(texto.strip()) < 20:
        raise HTTPException(400, "La transcripción está casi vacía, no hay nada que resumir")

    settings = get_settings()
    registro = ProviderRegistry(settings)
    proveedor = registro.get(_PROVEEDOR_RESUMEN)
    if not proveedor.is_configured():
        raise HTTPException(500, f"El proveedor '{_PROVEEDOR_RESUMEN}' no está configurado")

    mensajes = [
        ChatMessage(role="system", content=_INSTRUCCION_RESUMEN),
        ChatMessage(role="user", content=texto),
    ]
    try:
        resumen = await proveedor.chat(mensajes, model=_MODELO_RESUMEN, temperature=0.3)
    except ProviderError as e:
        raise HTTPException(502, f"No se pudo generar el resumen: {e}")

    nombre_resumen = fichero.rsplit(".", 1)[0] + "_resumen.txt"
    (_CARPETA / nombre_resumen).write_text(resumen, encoding="utf-8")

    return {"resumen": resumen, "fichero": nombre_resumen}

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
