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
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api import (clases_audio, clases_diapositivas, clases_ocr,
                     clases_podcast, clases_store)
from app.core.config import get_settings
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.tools.web_search import WebSearchClient

router = APIRouter(prefix="/clases", tags=["clases"])

# Mismo proveedor que la transcripcion (Groq), y mismo motivo: la clave ya
# esta configurada para el ciudadano "groq" de la Ciudad, sin cuenta nueva
# que crear. Es trabajo mecanico -condensar un texto largo en apuntes
# organizados-, asi que no hace falta un modelo caro para hacerlo bien.
_PROVEEDOR_RESUMEN = "groq"
_MODELO_RESUMEN = "llama-3.3-70b-versatile"

# Proveedores de IA para resumir y cruzar, POR ORDEN DE PREFERENCIA.
#
# Se prueban de arriba abajo hasta que uno conteste de verdad. Groq va el
# ultimo a proposito: su nivel gratuito solo admite 12.000 tokens por
# minuto y es el que primero se queda corto con textos largos.
# Para leer imagenes hace falta un proveedor con vision de verdad: no
# todos la tienen implementada en este proyecto (ver gemini_provider.py).
_PROVEEDORES_VISION = [
    ("gemini2", "gemini-3.6-flash"),
    ("gemini", "gemini-3.6-flash"),
]

# EL ORDEN IMPORTA MAS DE LO QUE PARECE.
#
# Antes esta lista empezaba por Cerebras. Cerebras tiene la clave puesta
# pero la cuota agotada, y Groq esta rozando su limite por minuto: los
# dos fallan, pero fallan DESPACIO -cada uno agota su espera interna de
# 60 segundos antes de rendirse-. Resultado: para llegar al proveedor
# que si funciona habia que esperar minutos con el boton mudo, y un
# fallo que tarda tres minutos en aparecer es indistinguible de un
# cuelgue.
#
# Gemini va primero porque es el que contesta de verdad hoy. Los demas
# quedan detras como red de seguridad.
_PROVEEDORES_CRUCE = [
    ("gemini2", "gemini-3.6-flash"),
    ("gemini", "gemini-3.6-flash"),
    ("glm", "glm-4.7-flash"),
    ("groq", "llama-3.3-70b-versatile"),
    ("cerebras", "gpt-oss-120b"),
]

# Cuanto se espera COMO MUCHO a cada proveedor antes de pasar al
# siguiente. Sin este tope, un proveedor colgado bloquea toda la cadena.
_ESPERA_POR_PROVEEDOR = 45.0

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


async def _pedir_a_la_ia(registro, mensajes, temperatura: float = 0.3) -> str:
    """
    Pide algo a la IA probando varios proveedores por orden.

    TENER CLAVE NO ES TENER CUOTA.

    Antes esto elegia UN proveedor al principio, preguntando si estaba
    "configurado". Pero is_configured() solo mira si hay una clave puesta:
    Cerebras tenia clave y la cuota agotada, asi que se elegia igualmente
    y luego moria con un error de pago. Comprobar la clave y dar por
    supuesto que funciona es la misma trampa de siempre -dar por bueno
    algo que no se ha verificado-.

    Ahora se prueba de verdad, uno detras de otro, y solo se rinde cuando
    han fallado todos. El ultimo error se conserva para poder contarlo.
    """
    # SE CUENTAN TODOS LOS INTENTOS, NO SOLO EL ULTIMO.
    #
    # Antes solo se guardaba el error del ultimo proveedor. Eso despista:
    # si Cerebras esta sin cuota y Groq al limite, ver unicamente "Groq
    # 413" hace pensar que el problema es el tamaño del texto, cuando en
    # realidad se han caido tres cosas distintas. Con la lista entera se
    # ve de un vistazo si falla uno o si no queda ninguno en pie.
    intentos: list[str] = []
    for nombre_prov, nombre_mod in _PROVEEDORES_CRUCE:
        try:
            proveedor = registro.get(nombre_prov)
        except KeyError:
            intentos.append(f"{nombre_prov}: no existe en el servidor")
            continue
        if not proveedor.is_configured():
            intentos.append(f"{nombre_prov}: sin clave configurada")
            continue
        try:
            # El tope de espera es lo que evita que un proveedor colgado
            # bloquee toda la cadena durante minutos.
            return await asyncio.wait_for(
                proveedor.chat(mensajes, model=nombre_mod, temperature=temperatura),
                timeout=_ESPERA_POR_PROVEEDOR,
            )
        except asyncio.TimeoutError:
            intentos.append(f"{nombre_prov}: no contestó en {int(_ESPERA_POR_PROVEEDOR)}s")
        except ProviderError as e:
            intentos.append(f"{nombre_prov}: {e}")
        except Exception as e:
            intentos.append(f"{nombre_prov}: {type(e).__name__} {e}")

    detalle = "\n".join(f"· {i}" for i in intentos) or "· no hay ningún proveedor configurado"
    raise HTTPException(502, "Ningún proveedor de IA ha podido con esto:\n" + detalle)


async def _leer_escaneado(registro, datos: bytes, nombre: str) -> dict:
    """
    Convierte un PDF escaneado en texto usando un modelo con vision.

    Devuelve tambien cuantas paginas se han leido y cuantas han fallado,
    porque "no salio texto" y "salieron 8 de 20 paginas" son cosas muy
    distintas y la persona tiene que poder distinguirlas.
    """
    try:
        imagenes = await clases_ocr.imagenes_en_hilo(datos)
    except Exception as e:
        return {"texto": "", "paginas_leidas": 0, "paginas_totales": 0, "fallos": 0, "error": str(e)}

    # Cuantas paginas tiene de verdad, para poder decir si se han
    # mirado todas o solo las primeras.
    try:
        import fitz
        doc = fitz.open(stream=datos, filetype="pdf")
        totales = doc.page_count
        doc.close()
    except Exception:
        totales = len(imagenes)

    partes, fallos = [], 0
    for i, imagen in enumerate(imagenes, start=1):
        leido = None
        for nombre_prov, nombre_mod in _PROVEEDORES_VISION:
            try:
                proveedor = registro.get(nombre_prov)
            except KeyError:
                continue
            if not proveedor.is_configured():
                continue
            try:
                leido = await proveedor.chat(
                    [ChatMessage(
                        role="user", content=clases_ocr.INSTRUCCION_OCR,
                        image_base64=imagen, image_mime="image/png",
                    )],
                    model=nombre_mod, temperature=0.0,
                )
                break
            except Exception:
                continue
        if leido and leido.strip():
            partes.append(f"--- Página {i} ---\n{leido.strip()}")
        else:
            fallos += 1

    return {
        "texto": "\n\n".join(partes),
        "paginas_leidas": len(partes),
        "paginas_totales": totales,
        "fallos": fallos,
    }


@router.post("/transcribir")
async def transcribir(audio: UploadFile = File(...), asignatura: str = "sin_asignatura",
                       propietario: str = ""):
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

        # SIEMPRE se recodifica primero: lo que graba el movil viene con
        # la cabecera incompleta y Whisper lo lee como silencio. Ver la
        # explicacion larga en clases_audio.normalizar.
        limpio = await clases_audio.normalizar_en_hilo(original, carpeta)

        duracion = await clases_audio.duracion_en_hilo(limpio)
        trozos = await clases_audio.partir_en_hilo(limpio, carpeta)
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
                        # El tipo se deduce del fichero que se manda de
                        # verdad, no del que subio el navegador: despues de
                        # normalizar ya no es el mismo formato.
                        files={"file": (trozo.name, datos, clases_audio.tipo_mime(trozo))},
                        data={"model": _MODELO, "response_format": "text",
                              "language": "es"},
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
    await clases_store.guardar(nombre, texto, propietario)

    return {
        "texto": texto,
        "fichero": nombre,
        "asignatura": asignatura,
        "fecha": ahora.isoformat(),
        "aviso": clases_audio.transcripcion_sospechosa(texto, duracion),
    }


@router.get("/listar")
async def listar(propietario: str = ""):
    """Las clases de este aparato, mas recientes primero -y de propina,
    las que quedaron sin dueño de antes de separar por aparato."""
    return {
        "clases": await clases_store.listar(propietario),
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

    registro = ProviderRegistry(get_settings())

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
            trozo = await _pedir_a_la_ia(registro, mensajes, temperatura=0.3)
            partes.append(trozo.strip())
            _PROGRESO[fichero] = {
                "estado": "trabajando",
                "porcentaje": int(i * 100 / total),
                "parte": i, "total": total,
            }
    except HTTPException as e:
        _PROGRESO[fichero] = {"estado": "error", "porcentaje": 0}
        # Si ya habia partes hechas se conservan: medio resumen de una clase
        # larga vale mucho mas que ninguno, siempre que se diga que esta a
        # medias.
        if not partes:
            raise
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

    registro = ProviderRegistry(get_settings())

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
            texto_ia = await _pedir_a_la_ia(registro, [
                ChatMessage(role="system", content=clases_diapositivas.INSTRUCCION_PARTE),
                ChatMessage(role="user", content=(
                    f"{cabecera}\n\n=== PARTE {i} DE {len(bloques)} DE LA CLASE ===\n{bloque}"
                )),
            ], temperatura=0.2)
            hallazgos.append(texto_ia.strip())
            _PROGRESO[fichero] = {
                "estado": "trabajando", "porcentaje": int(i * 100 / total),
                "parte": i, "total": total,
            }

        guia = await _pedir_a_la_ia(registro, [
            ChatMessage(role="system", content=clases_diapositivas.INSTRUCCION_CRUCE),
            ChatMessage(role="user", content=(
                cabecera + "\n\n=== LO OBSERVADO EN CADA PARTE DE LA CLASE ===\n"
                + "\n\n".join(hallazgos)
            )),
        ], temperatura=0.3)
    except HTTPException:
        _PROGRESO[fichero] = {"estado": "error", "porcentaje": 0}
        raise

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


INSTRUCCION_EXAMEN = (
    "Eres un profesor de medicina preparando preguntas de examen sobre una "
    "clase concreta. Tienes lo que se explico en clase y, si se te da, "
    "preguntas reales de examenes anteriores (MIR u otros) sobre esos temas.\n\n"
    "Escribe entre 8 y 15 preguntas TIPO TEST con 4 opciones (a, b, c, d), "
    "en el estilo del MIR: caso clinico corto cuando el tema lo permita, y "
    "pregunta directa cuando sea puro conocimiento.\n\n"
    "Para cada pregunta:\n"
    "- Marca la respuesta correcta.\n"
    "- Explica en dos lineas POR QUE es correcta y por que fallan las otras.\n"
    "- Añade al final '[Motivo: ...]' diciendo por que crees que esto puede "
    "caer: si es porque el profesor insistio, porque lo resalto en las "
    "diapositivas, o porque ha caido en examenes anteriores.\n\n"
    "REGLAS QUE NO PUEDES SALTARTE:\n"
    "- Solo preguntas sobre lo que se explico en ESTA clase. Nada de temas "
    "que el profesor no toco.\n"
    "- No inventes datos clinicos ni cifras que no aparezcan en el material.\n"
    "- Si tienes preguntas de examenes anteriores, usalas como modelo de "
    "ESTILO y de que se suele preguntar, pero no las copies tal cual.\n"
    "- Si tienes examenes anteriores reales, dilo explicitamente en la "
    "primera linea de tu respuesta: no lo des por sobreentendido ni lo "
    "omitas. Y cuando una pregunta este inspirada directamente en una de "
    "esas preguntas reales, dilo en su '[Motivo: ...]'.\n"
    "- Termina con una linea honesta: estas preguntas son un entrenamiento "
    "basado en lo que el profesor enfatizo, NO una prediccion del examen."
)


# Tope de texto de examenes que se manda a la IA. Con VARIOS examenes hay
# que repartirlo entre todos: si no, el primero se comeria el presupuesto
# entero y los demas no pintarian nada aunque se hayan subido.
_TOPE_EXAMENES = 18000


async def _leer_un_examen(
    registro: ProviderRegistry, pdf: UploadFile, diario: list[str],
) -> tuple[str, str]:
    """Saca el texto de UN examen. Devuelve (texto, como_describirlo).

    Texto vacio si no se ha podido leer -y en ese caso el motivo queda
    anotado en el diario, que es lo que luego se enseña en pantalla.
    """
    datos = await pdf.read()
    if not datos:
        diario.append(f"El PDF «{pdf.filename}» llegó vacío.")
        return "", ""

    kb = len(datos) // 1024
    try:
        extraido = await asyncio.to_thread(clases_diapositivas.extraer, datos)
        texto_pdf = extraido["texto"].strip()
        if texto_pdf:
            diario.append(
                f"Leído «{pdf.filename}» ({kb} KB, {extraido['paginas']} páginas): "
                f"{len(texto_pdf)} caracteres de texto."
            )
            return texto_pdf, f"{pdf.filename} ({extraido['paginas']} páginas)"

        # ES UN ESCANEO. Se lee con vision en vez de rendirse: los
        # examenes de una asignatura casi siempre llegan asi, y son justo
        # los que mas valen.
        diario.append(
            f"«{pdf.filename}» no tiene texto (es un escaneo). "
            f"Leyéndolo página a página con reconocimiento de imagen…"
        )
        leido = await _leer_escaneado(registro, datos, pdf.filename or "examen.pdf")
        if leido["texto"].strip():
            diario.append(
                f"Leídas {leido['paginas_leidas']} páginas del escaneo de «{pdf.filename}»"
                + (f" (de {leido['paginas_totales']} en total; el resto no se ha "
                   f"mirado para no disparar el gasto)"
                   if leido["paginas_totales"] > leido["paginas_leidas"] else "")
                + f": {len(leido['texto'])} caracteres."
            )
            if leido["fallos"]:
                diario.append(f"{leido['fallos']} páginas de «{pdf.filename}» no se pudieron leer.")
            return leido["texto"], f"{pdf.filename} (escaneado, {leido['paginas_leidas']} páginas)"

        diario.append(
            f"No se ha podido sacar texto del escaneo «{pdf.filename}». "
            f"Puede que la calidad sea muy baja."
        )
    except Exception as e:
        diario.append(f"No se pudo leer «{pdf.filename}»: {e}")
    return "", ""


async def _reunir_material_examenes(
    registro: ProviderRegistry, clase: str,
    pdfs: list[UploadFile] | None, buscar: bool,
) -> tuple[str, str, list[dict], list[str]]:
    """
    Consigue preguntas de examenes anteriores para dar de contexto real,
    en vez de dejar que la IA se las invente.

    DOS VIAS, PORQUE LA REALIDAD ES ASI.

    A veces se tienen los examenes anteriores en PDF y se suben. Y muchas
    otras veces no se tienen: los del MIR son publicos y estan en internet,
    pero los de una asignatura concreta a menudo no estan en ningun sitio.

    Si se suben PDFs, se usan TODOS -antes solo se admitia uno, y quien
    tiene los examenes de una asignatura los tiene por años, en ficheros
    separados: obligar a elegir uno solo es tirar la mitad del material
    que la persona ya tenia-. Si no hay ninguno, se busca en internet. Y
    si tampoco hay nada, se sigue adelante solo con la clase, diciendolo
    claramente. Lo que no se hace nunca es fingir que hay una fuente que
    no existe.

    Compartida entre /examen y /importancia: las dos necesitan exactamente
    lo mismo, y tenerlo en dos sitios es tenerlo desincronizado tarde o
    temprano.

    Devuelve (material_examenes, origen, fuentes, diario).
    """
    material_examenes = ""
    origen = "solo la clase"
    fuentes: list[dict] = []
    # Lo que ha pasado de verdad con lo que se ha intentado. Se devuelve a
    # la pantalla porque el primer intento se tragaba los fallos en
    # silencio: si el PDF no se podia leer, seguia adelante como si nada y
    # la persona se quedaba sin saber si su fichero se habia usado o no.
    diario: list[str] = []

    # 1. Examenes subidos a mano, si los hay. Se leen todos.
    reales = [p for p in (pdfs or []) if p is not None and p.filename]
    if reales:
        textos: list[str] = []
        nombres: list[str] = []
        for pdf in reales:
            texto, como = await _leer_un_examen(registro, pdf, diario)
            if texto:
                textos.append(f"--- {pdf.filename} ---\n{texto}")
                nombres.append(como)

        if textos:
            # El presupuesto se reparte a partes iguales, para que un
            # examen muy largo no deje sin sitio a los demas.
            porcion = max(1500, _TOPE_EXAMENES // len(textos))
            material_examenes = "\n\n".join(t[:porcion] for t in textos)[:_TOPE_EXAMENES]
            origen = (f"los exámenes que ha subido ({', '.join(nombres)})"
                      if len(nombres) == 1
                      else f"los {len(nombres)} exámenes que ha subido ({', '.join(nombres)})")
            diario.append(
                f"Se usan {len(textos)} examen(es), hasta {porcion} caracteres de cada uno."
            )

    # 2. Si no hay examenes propios utilizables, se busca en internet.
    if not material_examenes and buscar:
        buscador = WebSearchClient(get_settings().tavily_api_key)
        if not buscador.is_configured():
            diario.append("No hay búsqueda web configurada en el servidor.")
        else:
            temas = await _pedir_a_la_ia(registro, [
                ChatMessage(role="system", content=(
                    "Di en una sola linea, separados por comas, los 3 o 4 temas "
                    "medicos principales de esta clase. Solo los temas, nada mas."
                )),
                ChatMessage(role="user", content=clase[:6000]),
            ], temperatura=0.1)
            consulta = f"preguntas examen MIR {temas.strip()[:200]} con respuesta comentada"
            try:
                hallado, fuentes = await buscador.search_con_fuentes(consulta)
                if hallado.strip():
                    material_examenes = hallado[:8000]
                    origen = "preguntas encontradas en internet"
                    diario.append(f"Buscado en internet: «{consulta}».")
            except Exception as e:
                diario.append(f"La búsqueda en internet falló: {e}")

    return material_examenes, origen, fuentes, diario


@router.post("/examen/{fichero}")
async def examen(fichero: str, pdf: list[UploadFile] | None = File(None), buscar: bool = True):
    """
    Propone preguntas tipo examen sobre una clase. Ver
    `_reunir_material_examenes` para de donde sale el material de apoyo.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    clase = await clases_store.leer(fichero)
    if clase is None:
        raise HTTPException(404, "No existe esa clase")

    registro = ProviderRegistry(get_settings())
    material_examenes, origen, fuentes, diario = await _reunir_material_examenes(
        registro, clase, pdf, buscar)

    # PRESUPUESTO DE CARACTERES, PARA NO REPETIR EL 413 DE SIEMPRE.
    #
    # Meter la clase entera (hasta 25.000 caracteres) Y el examen entero
    # (hasta 18.000) a la vez es justo lo que hace saltar el limite de
    # Groq -12.000 tokens por minuto en su nivel gratuito-. Mientras
    # Cerebras o GLM esten disponibles no pasa nada, porque van primero y
    # admiten mucho mas; pero ya hemos visto a Cerebras caerse por cuota
    # agotada, y entonces esto acaba cayendo en Groq de todas formas. Con
    # examenes delante se recorta mas fuerte, para que quepa incluso en
    # el proveedor mas limitado.
    if material_examenes:
        entrada = "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:12000]
        entrada += "\n\n=== PREGUNTAS DE EXAMENES ANTERIORES SOBRE ESTOS TEMAS ===\n" + material_examenes[:8000]
        # EL FALLO ESTABA AQUI.
        #
        # La rama de "NO hay material" (mas abajo) siempre le decia a la IA
        # que lo avisara al principio de su respuesta. Esta rama, la de "SI
        # hay material", no decia nada parecido -asi que la IA escribia su
        # frase de apertura de memoria ("preguntas basadas en la clase") y
        # se olvidaba de mencionar que tambien tenia un examen real
        # delante. Quien preguntaba no tenia forma de saber, leyendo el
        # texto, si su PDF se habia usado de verdad. Ahora se le pide lo
        # mismo que a la otra rama, para que las dos sean simetricas.
        entrada += (
            "\n\n(SI hay preguntas de examenes anteriores disponibles, arriba. "
            "Dilo con claridad al principio del todo -por ejemplo: 'Estas "
            "preguntas se basan en la clase y en los examenes anteriores "
            "aportados'-. NO escribas que te basas 'solo en la clase' cuando "
            "tambien tienes examenes reales delante: seria falso y quien lo "
            "lea no podria confiar en que su documento se ha usado.)"
        )
    else:
        entrada = "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:25000]
        entrada += (
            "\n\n(NO hay preguntas de examenes anteriores disponibles. Genera las "
            "preguntas solo a partir de la clase, y dilo al principio del todo.)"
        )

    preguntas = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=INSTRUCCION_EXAMEN),
        ChatMessage(role="user", content=entrada),
    ], temperatura=0.4)

    # LA FUENTE VA PRIMERO, NO AL FINAL.
    #
    # Antes esto se guardaba DESPUES de las 10 preguntas: para verlo habia
    # que leer todo el documento hasta el final. Y en la respuesta que se
    # enseñaba al momento, la procedencia ni siquiera iba pegada al texto
    # -cada pantalla la montaba por su cuenta, y era facil que se quedara
    # fuera-. Ahora la cabecera es UNA FRASE FIJA que no depende de que la
    # IA se acuerde de decirla, y va delante: la respuesta a "¿esto ha
    # usado mi documento?" se ve sin buscar.
    cabecera = f"📎 Fuente de estas preguntas: {origen}."
    if fuentes:
        cabecera += "\n" + "\n".join(f"   • {f['titulo']}: {f['url']}" for f in fuentes)
    cabecera += "\n" + "─" * 44

    pie = "\n\n---"
    for linea in diario:
        pie += f"\n({linea})"

    nombre = fichero.rsplit(".", 1)[0] + "_examen.txt"
    await clases_store.guardar(nombre, cabecera + "\n\n" + preguntas + pie)

    return {
        "preguntas": preguntas, "cabecera": cabecera, "fichero": nombre,
        "origen": origen, "fuentes": fuentes, "diario": diario,
    }


# =====================================================================
# QUE CONCEPTOS INSISTE MAS EL PROFESOR, DE UN VISTAZO
# =====================================================================
#
# La idea original pedia interpretar entonacion, pausas, "puntualizacion"
# al hablar. Eso queda fuera A PROPOSITO: para eso hace falta analizar el
# AUDIO (volumen, ritmo, tono), no el texto transcrito, y aun teniendolo
# la relacion entre "el profesor sube la voz" y "esto cae en el examen"
# es debil -se puede subir la voz por mil motivos que no tienen nada que
# ver con la importancia del concepto-. Meterlo habria sido prometer una
# fiabilidad que no existe.
#
# Lo que SI se sostiene, y es lo que se usa aqui:
#   - Que el profesor vuelva sobre un concepto varias veces en vez de
#     nombrarlo una sola vez de pasada, SI se ve en el texto.
#   - Que el concepto aparezca en examenes anteriores reales, SI se puede
#     comprobar -reutilizando exactamente la misma busqueda que ya usa
#     "Posibles preguntas".
#
# Con esas dos señales, cada concepto se colorea rojo (insistencia clara
# o ya ha caido antes), amarillo (se explica pero de pasada una vez) o
# verde (mencion breve, de contexto). Es una lista visual para repasar
# rapido, no una prediccion del examen -y eso se dice tambien en pantalla.

INSTRUCCION_IMPORTANCIA = (
    "Eres un profesor de medicina ayudando a un alumno a priorizar que "
    "repasar de una clase de cara a un examen tipo MIR.\n\n"

    "Tienes la clase transcrita y, si se te da, preguntas reales de "
    "examenes anteriores sobre estos temas.\n\n"

    "TAREA: identifica los conceptos concretos que trata la clase "
    "-enfermedades, sindromes, farmacos, criterios diagnosticos, valores "
    "de referencia...- y da a cada uno un color:\n\n"
    "- rojo: el profesor vuelve sobre el varias veces a lo largo de la "
    "clase, insiste o lo repite con distintas palabras, O aparece en las "
    "preguntas de examenes anteriores que se te han dado.\n"
    "- amarillo: se explica con algo de detalle pero se menciona una "
    "sola vez, sin que el profesor vuelva sobre ello.\n"
    "- verde: se nombra de pasada, como parte de una enumeracion o de "
    "contexto, sin detenerse.\n\n"

    "REGLAS:\n"
    "- Solo conceptos que aparezcan de verdad en la clase. No inventes "
    "ninguno ni completes con lo que 'suele' explicarse en ese tema.\n"
    "- Nombres cortos, de 2 a 6 palabras, como para una lista de repaso "
    "-no una frase ni una explicacion-.\n"
    "- No repitas el mismo concepto con distintas palabras.\n"
    "- Entre 8 y 20 conceptos. Si la clase da para menos, pon menos: no "
    "rellenes por rellenar.\n\n"

    "FORMATO DE RESPUESTA: SOLO un JSON, nada de texto antes ni despues, "
    "nada de bloque de codigo con ```. Una lista de objetos exactamente "
    "asi:\n"
    '[{"concepto": "Sindrome de Wolff-Parkinson-White", "color": "rojo"}, '
    '{"concepto": "Bloqueo AV de primer grado", "color": "amarillo"}]\n\n'
    'El campo "color" solo puede valer "rojo", "amarillo" o "verde". '
    "Nada de explicaciones, nada de motivos, nada de texto fuera del JSON."
)


def _parsear_conceptos(bruto: str) -> list[dict]:
    """
    Saca la lista de conceptos de lo que ha respondido la IA.

    Se pide JSON puro, pero conviene no fiarse a ciegas: a veces se cuela
    un bloque ```json``` alrededor, o una frase de presentacion delante.
    Se busca el primer '[' y el ultimo ']' del texto en vez de exigir un
    JSON perfecto -y cualquier objeto que no tenga la forma esperada se
    descarta en vez de romper toda la lista.
    """
    texto = re.sub(r"^```[a-z]*\s*\n?|\n?```\s*$", "", bruto.strip())
    ini, fin = texto.find("["), texto.rfind("]")
    if ini == -1 or fin == -1 or fin < ini:
        return []
    try:
        datos = json.loads(texto[ini:fin + 1])
    except Exception:
        return []
    if not isinstance(datos, list):
        return []
    validos = []
    for d in datos:
        if not isinstance(d, dict):
            continue
        concepto = str(d.get("concepto", "")).strip()
        color = str(d.get("color", "")).strip().lower()
        if concepto and color in ("rojo", "amarillo", "verde"):
            validos.append({"concepto": concepto, "color": color})
    return validos


@router.post("/importancia/{fichero}")
async def importancia(fichero: str, pdf: list[UploadFile] | None = File(None), buscar: bool = True):
    """
    Lista visual de conceptos de la clase, coloreados segun lo probable
    que sea que caigan en examen. Ver el bloque de comentarios de arriba
    para que se ha dejado fuera a proposito y por que.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    clase = await clases_store.leer(fichero)
    if clase is None:
        raise HTTPException(404, "No existe esa clase")

    registro = ProviderRegistry(get_settings())
    material_examenes, origen, fuentes, diario = await _reunir_material_examenes(
        registro, clase, pdf, buscar)

    if material_examenes:
        entrada = ("=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:12000] +
                   "\n\n=== PREGUNTAS DE EXAMENES ANTERIORES SOBRE ESTOS TEMAS ===\n" +
                   material_examenes[:8000])
    else:
        entrada = "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:25000]

    bruto = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=INSTRUCCION_IMPORTANCIA),
        ChatMessage(role="user", content=entrada),
    ], temperatura=0.2)

    conceptos = _parsear_conceptos(bruto)
    if not conceptos:
        # Mejor decir "no ha salido bien" que enseñar una lista vacia sin
        # explicacion, como si la clase no tuviera ningun concepto.
        diario.append("La IA no ha devuelto una lista con el formato esperado.")

    return {
        "conceptos": conceptos,
        "origen": origen,
        "fuentes": fuentes,
        "diario": diario,
    }


# =====================================================================
# TABLAS COMPARATIVAS
# =====================================================================
#
# En medicina lo que mas se confunde -y lo que mas se pregunta- son cosas
# que se parecen: dos anemias, tres shocks, cuatro glomerulonefritis. En
# un texto corrido esas diferencias quedan repartidas en parrafos
# distintos y hay que ir juntandolas mentalmente. En una tabla se ven de
# golpe. Por eso esto es un boton aparte y no parte del resumen: no toda
# clase tiene material comparable, y forzar tablas donde no las hay solo
# produce tablas vacias de relleno.
#
# Si se suben las diapositivas, se cruzan: lo que el profesor resalta
# marca que columnas le importan de verdad.

INSTRUCCION_TABLAS = (
    "Eres un profesor de medicina que prepara material de repaso para un "
    "alumno. A partir de una clase transcrita, construyes TABLAS "
    "COMPARATIVAS de lo que se presta a confusion.\n\n"

    "QUE COMPARAR: cosas del mismo tipo que el alumno pueda mezclar "
    "-enfermedades parecidas, tipos de un mismo sindrome, farmacos de la "
    "misma familia, pruebas diagnosticas alternativas, criterios que se "
    "confunden entre si-.\n\n"

    "FORMATO: tablas en markdown, con | y guiones. La primera columna es "
    "lo que se compara; las siguientes, los criterios que de verdad las "
    "distinguen (clinica, diagnostico, tratamiento, pronostico... lo que "
    "aplique en cada caso).\n\n"
    "Antes de cada tabla, un titulo corto con ## diciendo que compara.\n"
    "Despues de cada tabla, UNA sola linea empezando por 'Clave:' con lo "
    "unico que hay que recordar para no confundirlas.\n\n"

    "REGLAS:\n"
    "- SOLO con lo que aparece en la clase. Si de un elemento no se dijo "
    "un dato, escribe 'no se dijo en clase' en esa celda. NO lo completes "
    "con lo que sabes: el alumno tiene que poder distinguir lo que entra "
    "de lo que no.\n"
    "- Si la clase no da para ninguna comparacion clara, dilo en una "
    "linea y no te inventes tablas de relleno.\n"
    "- Celdas cortas, de pocas palabras. Una tabla que no se lee de un "
    "vistazo no sirve para lo que sirve una tabla.\n"
    "- Entre 2 y 6 tablas. Mejor pocas y utiles que muchas y forzadas.\n"
    "- Nada de introduccion ni de despedida: empieza directamente por el "
    "primer titulo."
)


@router.post("/tablas/{fichero}")
async def tablas(fichero: str, pdf: UploadFile | None = File(None)):
    """
    Tablas comparativas de la clase. Si se suben las diapositivas, se
    usan para saber que aspectos resalta el profesor.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    clase = await clases_store.leer(fichero)
    if clase is None:
        raise HTTPException(404, "No existe esa clase")

    registro = ProviderRegistry(get_settings())
    diario: list[str] = []
    cabecera_diapos = ""

    if pdf is not None and pdf.filename:
        datos = await pdf.read()
        if not datos:
            diario.append(f"El PDF «{pdf.filename}» llegó vacío.")
        else:
            try:
                extraido = await asyncio.to_thread(clases_diapositivas.extraer, datos)
                resaltados = extraido["resaltados"][:80]
                if resaltados:
                    cabecera_diapos = (
                        "=== LO QUE EL PROFESOR RESALTA EN SUS DIAPOSITIVAS ===\n"
                        "(dale mas peso a estos aspectos al elegir las columnas)\n"
                        + "\n".join(f"- {r}" for r in resaltados) + "\n\n"
                    )
                    diario.append(
                        f"Leídas las diapositivas «{pdf.filename}» "
                        f"({extraido['paginas']} páginas, {len(resaltados)} elementos resaltados)."
                    )
                else:
                    diario.append(
                        f"«{pdf.filename}» se ha leído pero no tiene nada resaltado "
                        f"que aprovechar."
                    )
            except Exception as e:
                diario.append(f"No se pudo leer «{pdf.filename}»: {e}")

    texto = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=INSTRUCCION_TABLAS),
        ChatMessage(role="user", content=(
            cabecera_diapos + "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:20000]
        )),
    ], temperatura=0.3)

    nombre = fichero.rsplit(".", 1)[0] + "_tablas.txt"
    await clases_store.guardar(nombre, texto)

    return {"tablas": texto, "fichero": nombre, "diario": diario}


# =====================================================================
# PREGUNTARLE UNA DUDA A LA CLASE
# =====================================================================
#
# Estudiando surgen dudas concretas -"¿por que en ese caso se da el
# farmaco X y no el Y?"- y buscarlas fuera devuelve la respuesta general
# del libro, que muchas veces NO es la que dio el profesor. Y en un
# examen se corrige lo que dijo el profesor.
#
# Por eso esto responde SIGUIENDO EL HILO DE LA CLASE: usa el enfoque,
# el criterio y hasta las palabras del profesor. Si la duda toca algo que
# no se explico, lo dice y lo separa claramente en vez de mezclarlo, para
# que el alumno sepa siempre que parte viene de clase y que parte no.

INSTRUCCION_DUDA = (
    "Eres un profesor de medicina resolviendo la duda de un alumno. "
    "RESPONDE SIEMPRE a lo que se te pregunta.\n\n"

    "Tienes delante la transcripcion de una clase que el alumno acaba de "
    "ver, y a veces tambien informacion de internet. La clase es tu "
    "PUNTO DE PARTIDA, no tu limite.\n\n"

    "COMO USAR CADA COSA:\n"
    "- Si la duda se trato en clase: responde siguiendo el hilo del "
    "profesor -su enfoque, sus criterios, sus ejemplos-, porque es lo "
    "que se corregira en el examen. Enlazalo: «como se comento al hablar "
    "de...».\n"
    "- Si la duda NO se trato en clase, o se trato de pasada: "
    "RESPONDELA IGUAL, con tu conocimiento y con lo que se te haya dado "
    "de internet. Avisa en una linea con «Esto no se vio en clase» y "
    "sigue. Nunca te niegues a contestar por eso.\n"
    "- Si la duda no tiene que ver con la clase: contestala tambien. El "
    "alumno pregunta lo que necesita, no lo que toca.\n\n"

    "LO QUE NO PUEDES HACER:\n"
    "- NO atribuyas al profesor nada que no este en la transcripcion. "
    "Esto es lo mas grave: el alumno estudia para un examen que corrige "
    "ese profesor. Si no lo dijo, se dice que no lo dijo.\n"
    "- NO empieces negandote ni diciendo de que puedes hablar. Ve "
    "directo a la respuesta.\n\n"

    "ESTILO: directo y breve, es una duda concreta y no una leccion. "
    "Nada de despedidas ni de ofrecerte a seguir ayudando."
)


@router.post("/preguntar/{fichero}")
async def preguntar(fichero: str, duda: str = Form(...), buscar: bool = Form(True)):
    """
    Responde una duda del alumno.

    La clase es la REFERENCIA, no la frontera. La primera version decia
    "eres el profesor de esta clase" y el modelo se lo tomo al pie de la
    letra: se negaba a contestar cualquier cosa que el profesor no
    hubiera tocado, que es justo cuando mas falta hace preguntar. Ahora
    responde siempre, y ademas puede mirar en internet.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    if len(duda.strip()) < 3:
        raise HTTPException(400, "Escriba la duda")
    clase = await clases_store.leer(fichero)
    if clase is None:
        raise HTTPException(404, "No existe esa clase")

    registro = ProviderRegistry(get_settings())
    duda = duda.strip()[:1500]

    # Busqueda en internet sobre la duda. Si falla o no esta configurada,
    # se contesta igual con la clase y el conocimiento del modelo: quedar
    # sin respuesta por no haber internet seria peor que la respuesta.
    hallado, fuentes = "", []
    if buscar:
        buscador = WebSearchClient(get_settings().tavily_api_key)
        if buscador.is_configured():
            try:
                hallado, fuentes = await buscador.search_con_fuentes(duda)
            except Exception:
                hallado, fuentes = "", []

    entrada = "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:18000]
    if hallado.strip():
        entrada += ("\n\n=== INFORMACION DE INTERNET SOBRE LA DUDA ===\n"
                    "(usala si la clase no cubre la duda; si contradice a la "
                    "clase, di las dos cosas y señala cual es cual)\n"
                    + hallado[:6000])
    entrada += "\n\n=== DUDA DEL ALUMNO ===\n" + duda

    respuesta = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=INSTRUCCION_DUDA),
        ChatMessage(role="user", content=entrada),
    ], temperatura=0.3)

    return {"respuesta": respuesta.strip(), "fuentes": fuentes}


@router.delete("/borrar/{fichero}")
async def borrar(fichero: str, propietario: str = ""):
    """
    Borra una clase concreta, solo la que se pida y solo si es tuya (o si
    quedo sin dueño de antes de separar por aparato).

    Existe porque acumular grabaciones de prueba junto a las de verdad
    acaba haciendo la lista inservible, y no tener forma de limpiar
    obliga a borrarlo todo o a no borrar nada.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    if not await clases_store.borrar(fichero, propietario):
        raise HTTPException(404, "No existe esa clase, o no es suya")
    return {"borrado": fichero}


def _sanear(texto: str) -> str:
    permitido = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(c if c in permitido else "_" for c in texto)[:40] or "sin_asignatura"


# =====================================================================
# LA CLASE EN PODCAST, PARA ESCUCHARLA CONDUCIENDO
# =====================================================================
#
# Va en DOS PASOS a proposito, igual que el dictado en la app de
# documentos:
#
#   1. /guion-podcast  -> devuelve el texto de la conversacion
#   2. /audio-podcast  -> lo convierte en mp3
#
# Podrian ir juntos y seria un boton menos. No se hace porque generar la
# voz tarda bastante, y si el guion ha salido mal habria que esperar dos
# veces. Ademas el guion vale por si solo: se puede leer, corregir, o
# pegar en otra herramienta de voz mejor.

@router.post("/guion-podcast/{fichero}")
async def guion_podcast(fichero: str):
    """Convierte unos apuntes en un diálogo de dos voces para escuchar."""
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe eso")
    texto = await clases_store.leer(fichero)
    if not texto:
        raise HTTPException(404, "No existe eso")
    if len(texto.strip()) < 120:
        raise HTTPException(400, "Hay muy poco texto para hacer un pódcast")

    registro = ProviderRegistry(get_settings())
    guion = await _pedir_a_la_ia(
        registro,
        [ChatMessage(role="system", content=clases_podcast.INSTRUCCION_GUION),
         ChatMessage(role="user", content=texto[:18000])],
        temperatura=0.55,   # algo mas suelto: es una conversacion, no un informe
    )
    guion = guion.strip()[:clases_podcast.MAX_CARACTERES_GUION]

    nombre = fichero.rsplit(".", 1)[0].replace("_resumen", "") + "_podcast.txt"
    await clases_store.guardar(nombre, guion)

    turnos = clases_podcast.partir_en_turnos(guion)
    return {
        "guion": guion,
        "fichero": nombre,
        "turnos": len(turnos),
        # Cinco palabras por segundo es el ritmo normal de habla en
        # español. Sirve para decir cuanto va a durar ANTES de generarlo.
        "minutos": max(1, round(len(guion.split()) / 150)),
    }


@router.post("/audio-podcast/{fichero}")
async def audio_podcast(fichero: str):
    """Genera el mp3 del pódcast, para descargarlo y oírlo en el coche."""
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe eso")
    guion = await clases_store.leer(fichero)
    if not guion:
        raise HTTPException(404, "Primero hay que crear el guion")

    try:
        audio = await clases_podcast.sintetizar(guion)
    except ImportError:
        raise HTTPException(
            503, "El servidor no tiene instalados los generadores de voz. "
                 "El guion sí está: puede leerlo o pegarlo en otra herramienta.")
    except Exception as e:
        # Aquí solo se llega si han fallado los DOS motores de voz (el
        # bueno y el de respaldo). NUNCA dejar al usuario sin saber que ha
        # pasado. El guion ya lo tiene, asi que esto no es perderlo todo:
        # es no poder oirlo, de momento.
        raise HTTPException(
            502, f"No se pudo generar la voz por ningún medio ({type(e).__name__}). "
                 f"El guion sigue guardado y puede leerlo o pegarlo en otra "
                 f"herramienta de audio. Puede volver a intentarlo más tarde.")

    nombre_mp3 = fichero.rsplit(".", 1)[0] + ".mp3"
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{nombre_mp3}"'},
    )
