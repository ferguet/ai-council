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

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api import clases_audio, clases_diapositivas, clases_store
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

# Para el cruce con las diapositivas, por orden de preferencia. Cerebras
# va primero porque su nivel gratuito es mucho mas holgado por minuto y
# ningun ciudadano de la Ciudad lo usa, asi que no compite por cuota con
# nada mas del proyecto. Si no estuviera configurado, se cae a Groq.
_PROVEEDORES_CRUCE = [
    ("cerebras", "gpt-oss-120b"),
    ("glm", "glm-4.7-flash"),
    ("groq", "llama-3.3-70b-versatile"),
]

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

    # YA NO SE RECHAZAN LAS CLASES LARGAS.
    #
    # Antes, un audio de mas de 25 MB se devolvia con un "pártalo usted",
    # que es cargarle a la persona un trabajo que puede hacer la maquina,
    # y ademas justo cuando mas falta hace: una clase larga es la que mas
    # merece la pena tener transcrita.
    #
    # Ahora se parte aqui en trozos de 10 minutos, se transcribe cada uno
    # y se une el texto. El limite de 25 MB de Whisper sigue existiendo,
    # pero lo lleva el servidor en vez de la persona.
    with clases_audio.carpeta_temporal() as tmp:
        carpeta = Path(tmp)
        sufijo = Path(audio.filename or "clase.m4a").suffix or ".m4a"
        original = carpeta / f"entera{sufijo}"
        original.write_bytes(contenido)

        trozos = await clases_audio.partir_en_hilo(original, carpeta)
        partes: list[str] = []

        for i, trozo in enumerate(trozos, start=1):
            datos = trozo.read_bytes()
            if len(datos) > 25 * 1024 * 1024:
                raise HTTPException(
                    413,
                    f"Un trozo del audio sigue pesando más de 25 MB aunque se ha "
                    f"partido. Probablemente el audio venga con una calidad muy "
                    f"alta; conviene reducirla antes de subirlo."
                )
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        _GROQ_TRANSCRIBE_URL,
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        files={"file": (trozo.name, datos, audio.content_type or "audio/mp4")},
                        data={"model": _MODELO, "response_format": "text"},
                    )
            except httpx.RequestError as e:
                raise HTTPException(502, f"No se pudo contactar con Groq: {e}")

            if resp.status_code != 200:
                # Si ya hay trozos transcritos, se conserva lo conseguido y
                # se avisa de donde se corto: media clase es mucho mejor que
                # ninguna, siempre que quede claro que esta incompleta.
                if partes:
                    partes.append(
                        f"\n\n[AVISO: la transcripción se cortó aquí, en el trozo {i} "
                        f"de {len(trozos)}. El resto de la clase no se pudo transcribir.]"
                    )
                    break
                raise HTTPException(502, f"Groq devolvió un error: {resp.text[:300]}")

            partes.append(resp.text.strip())

        texto = "\n\n".join(partes)

    ahora = datetime.now(timezone.utc)
    nombre = f"{ahora.strftime('%Y-%m-%d_%H%M')}_{_sanear(asignatura)}.txt"
    await clases_store.guardar(nombre, texto)

    return {
        "texto": texto,
        "fichero": nombre,
        "asignatura": asignatura,
        "fecha": ahora.isoformat(),
    }


@router.get("/listar")
async def listar():
    """Las clases ya transcritas, mas recientes primero."""
    return {
        "clases": await clases_store.listar(),
        "guardado_en": await clases_store.donde_se_guarda(),
    }


@router.get("/leer/{fichero}")
async def leer(fichero: str):
    """El texto de una clase concreta, para volver a consultarlo."""
    # Evitar salir de la carpeta con "../algo": solo nombres de fichero
    # sueltos, nunca rutas.
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    texto = await clases_store.leer(fichero)
    if texto is None:
        raise HTTPException(404, "No existe esa clase")
    return {"texto": texto}


# COMO VA EL RESUMEN DE CADA CLASE, PARA PODER ENSEÑARLO.
#
# Resumir una clase larga tarda minutos, y hasta ahora la persona se
# quedaba mirando un boton sin saber si estaba trabajando, si se habia
# colgado, o si no habia llegado a empezar. Un trabajo largo que no dice
# como va es indistinguible de uno roto.
#
# Aqui se guarda por que parte va cada resumen en marcha. Es un diccionario
# en memoria a proposito: si el servidor se reinicia, el resumen se ha
# perdido de todas formas, asi que no tiene sentido guardarlo en disco.
_PROGRESO: dict[str, dict] = {}

# Trozos de texto para resumir por partes. Una clase de dos horas son
# decenas de miles de palabras y NO caben en una sola peticion al modelo:
# aunque cupieran, resumir tanto de golpe da resumenes pobres, porque el
# modelo se queda con lo general y pierde el detalle.
_LETRAS_POR_BLOQUE = 12000


def _partir_texto(texto: str) -> list[str]:
    return _partir_texto_a(texto, _LETRAS_POR_BLOQUE)


def _partir_texto_a(texto: str, tope: int) -> list[str]:
    """Corta por parrafos, nunca a mitad de frase."""
    _LETRAS_POR_BLOQUE = tope
    if len(texto) <= _LETRAS_POR_BLOQUE:
        return [texto]
    bloques, actual = [], ""
    for parrafo in texto.split("\n"):
        if len(actual) + len(parrafo) > _LETRAS_POR_BLOQUE and actual:
            bloques.append(actual)
            actual = ""
        actual += parrafo + "\n"
    if actual.strip():
        bloques.append(actual)
    return bloques


@router.get("/progreso/{fichero}")
async def progreso(fichero: str):
    """Por que parte va el resumen de esa clase. La app lo consulta cada pocos segundos."""
    return _PROGRESO.get(fichero, {"estado": "parado", "porcentaje": 0})


@router.post("/resumir/{fichero}")
async def resumir(fichero: str):
    """
    Convierte una transcripcion en apuntes organizados.

    Si la clase es larga se resume POR PARTES y se van uniendo, avisando
    del avance en /progreso para que la app pueda enseñar por donde va.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    texto = await clases_store.leer(fichero)
    if texto is None:
        raise HTTPException(404, "No existe esa clase")
    if len(texto.strip()) < 20:
        raise HTTPException(400, "La transcripción está casi vacía, no hay nada que resumir")

    settings = get_settings()
    registro = ProviderRegistry(settings)
    proveedor = registro.get(_PROVEEDOR_RESUMEN)
    if not proveedor.is_configured():
        raise HTTPException(500, f"El proveedor '{_PROVEEDOR_RESUMEN}' no está configurado")

    bloques = _partir_texto(texto)
    total = len(bloques)
    _PROGRESO[fichero] = {"estado": "trabajando", "porcentaje": 0, "parte": 0, "total": total}

    partes: list[str] = []
    try:
        for i, bloque in enumerate(bloques, start=1):
            aviso = "" if total == 1 else (
                f"\n\nEsto es la parte {i} de {total} de la clase. Resume SOLO "
                f"esta parte, sin repetir lo de las otras y sin escribir "
                f"conclusiones finales salvo que sea la última parte."
            )
            mensajes = [
                ChatMessage(role="system", content=_INSTRUCCION_RESUMEN + aviso),
                ChatMessage(role="user", content=bloque),
            ]
            trozo = await proveedor.chat(mensajes, model=_MODELO_RESUMEN, temperature=0.3)
            partes.append(trozo.strip())
            _PROGRESO[fichero] = {
                "estado": "trabajando",
                "porcentaje": int(i * 100 / total),
                "parte": i, "total": total,
            }
    except ProviderError as e:
        _PROGRESO[fichero] = {"estado": "error", "porcentaje": 0, "mensaje": str(e)}
        # Si ya habia partes hechas se conservan: medio resumen de una clase
        # larga vale mucho mas que ninguno, siempre que se diga que esta a
        # medias.
        if not partes:
            raise HTTPException(502, f"No se pudo generar el resumen: {e}")
        partes.append(
            f"\n\n[AVISO: el resumen se cortó en la parte {len(partes)} de {total}. "
            f"El resto de la clase no llegó a resumirse.]"
        )

    resumen = "\n\n".join(partes)
    nombre_resumen = fichero.rsplit(".", 1)[0] + "_resumen.txt"
    await clases_store.guardar(nombre_resumen, resumen)
    _PROGRESO[fichero] = {"estado": "hecho", "porcentaje": 100, "parte": total, "total": total}

    return {"resumen": resumen, "fichero": nombre_resumen, "partes": total}


@router.post("/diapositivas/{fichero}")
async def diapositivas(fichero: str, pdf: UploadFile = File(...)):
    """
    Cruza las diapositivas del profesor con lo que dijo en clase.

    SE HACE POR PARTES, Y NO POR CAPRICHO.

    El primer intento mandaba las diapositivas enteras y la clase entera en
    una sola peticion, y el proveedor lo rechazo: su plan gratuito admite
    12.000 tokens por minuto y aquello pedia 17.000. Pero el limite solo
    saco a la luz un problema que ya estaba ahi: meter cincuenta mil
    caracteres de golpe da respuestas pobres, porque el modelo se queda con
    lo general y pierde justo el detalle que se le esta pidiendo.

    Asi que se recorre la clase por bloques, cruzando cada uno con lo
    resaltado del PDF, y al final se junta todo en la guia de prioridades.
    Ademas permite decir por donde va, que es lo que se pidio.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    transcripcion = await clases_store.leer(fichero)
    if transcripcion is None:
        raise HTTPException(404, "No existe esa clase")

    datos = await pdf.read()
    if not datos:
        raise HTTPException(400, "El PDF ha llegado vacío")

    try:
        extraido = await asyncio.to_thread(clases_diapositivas.extraer, datos)
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer el PDF: {e}")

    if not extraido["texto"].strip():
        raise HTTPException(
            400,
            "Este PDF no tiene texto: probablemente sean diapositivas "
            "escaneadas como imagen. De esas no se puede sacar el formato."
        )

    settings = get_settings()
    registro = ProviderRegistry(settings)

    # Se prueba primero un proveedor con mas margen por minuto, y si no
    # esta configurado se usa el de siempre. El limite de Groq (12.000
    # tokens/minuto) es justo el que hizo fallar esto la primera vez.
    proveedor = None
    modelo = _MODELO_RESUMEN
    for nombre_prov, nombre_mod in _PROVEEDORES_CRUCE:
        p = registro.get(nombre_prov)
        if p.is_configured():
            proveedor, modelo = p, nombre_mod
            break
    if proveedor is None:
        raise HTTPException(500, "No hay ningún proveedor de IA configurado")

    # Lista de resaltados, recortada: es la parte que se repite en TODAS
    # las peticiones, asi que cuanto mas corta, mas sitio queda para la
    # clase en cada bloque.
    resaltados = extraido["resaltados"][:120]
    cabecera = (
        "=== LO QUE EL PROFESOR RESALTA EN SUS DIAPOSITIVAS ===\n"
        + ("\n".join(f"- {r}" for r in resaltados) if resaltados
           else "(no se ha detectado nada resaltado en este PDF)")
    )

    bloques = _partir_texto_a(transcripcion, 6000)
    total = len(bloques) + 1  # +1 por la union final
    _PROGRESO[fichero] = {"estado": "trabajando", "porcentaje": 0, "parte": 0, "total": total}

    hallazgos: list[str] = []
    try:
        for i, bloque in enumerate(bloques, start=1):
            texto_ia = await proveedor.chat(
                [
                    ChatMessage(role="system", content=clases_diapositivas.INSTRUCCION_PARTE),
                    ChatMessage(role="user", content=(
                        f"{cabecera}\n\n=== PARTE {i} DE {len(bloques)} DE LA CLASE ===\n{bloque}"
                    )),
                ],
                model=modelo, temperature=0.2,
            )
            hallazgos.append(texto_ia.strip())
            _PROGRESO[fichero] = {
                "estado": "trabajando", "porcentaje": int(i * 100 / total),
                "parte": i, "total": total,
            }

        guia = await proveedor.chat(
            [
                ChatMessage(role="system", content=clases_diapositivas.INSTRUCCION_CRUCE),
                ChatMessage(role="user", content=(
                    cabecera + "\n\n=== LO OBSERVADO EN CADA PARTE DE LA CLASE ===\n"
                    + "\n\n".join(hallazgos)
                )),
            ],
            model=modelo, temperature=0.3,
        )
    except ProviderError as e:
        _PROGRESO[fichero] = {"estado": "error", "porcentaje": 0, "mensaje": str(e)}
        raise HTTPException(502, f"No se pudo cruzar: {e}")

    _PROGRESO[fichero] = {"estado": "hecho", "porcentaje": 100, "parte": total, "total": total}

    nombre = fichero.rsplit(".", 1)[0] + "_prioridades.txt"
    await clases_store.guardar(nombre, guia)

    return {
        "guia": guia,
        "fichero": nombre,
        "resaltados": len(resaltados),
        "paginas": extraido["paginas"],
        "recortado": extraido["recortado"],
        "partes": len(bloques),
    }


@router.delete("/borrar/{fichero}")
async def borrar(fichero: str):
    """
    Borra una clase concreta, solo la que se pida.

    Existe porque acumular grabaciones de prueba junto a las de verdad
    acaba haciendo la lista inservible, y no tener forma de limpiar
    obliga a borrarlo todo o a no borrar nada.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    if not await clases_store.borrar(fichero):
        raise HTTPException(404, "No existe esa clase")
    return {"borrado": fichero}


def _sanear(texto: str) -> str:
    permitido = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(c if c in permitido else "_" for c in texto)[:40] or "sin_asignatura"
