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

from app.api import clases_audio, clases_diapositivas, clases_ocr, clases_store
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
    ultimo = None
    for nombre_prov, nombre_mod in _PROVEEDORES_CRUCE:
        try:
            proveedor = registro.get(nombre_prov)
        except KeyError:
            continue
        if not proveedor.is_configured():
            continue
        try:
            return await proveedor.chat(mensajes, model=nombre_mod, temperature=temperatura)
        except ProviderError as e:
            ultimo = f"{nombre_prov}: {e}"
            continue
        except Exception as e:
            ultimo = f"{nombre_prov}: {e}"
            continue
    raise HTTPException(
        502,
        "Ningún proveedor de IA ha podido con esto. "
        f"El último dijo: {ultimo or 'no hay ninguno configurado'}"
    )


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


@router.post("/examen/{fichero}")
async def examen(fichero: str, pdf: UploadFile | None = File(None), buscar: bool = True):
    """
    Propone preguntas tipo examen sobre una clase.

    DOS VIAS, PORQUE LA REALIDAD ES ASI.

    A veces se tienen los examenes anteriores en PDF y se suben. Y muchas
    otras veces no se tienen: los del MIR son publicos y estan en internet,
    pero los de una asignatura concreta a menudo no estan en ningun sitio.

    Si se sube un PDF, se usa. Si no, se busca en internet lo que haya
    sobre esos temas. Y si tampoco hay nada, se generan preguntas solo con
    la clase -que sigue siendo util para repasar- diciendo claramente que
    van sin respaldo de examenes reales. Lo que no se hace nunca es
    fingir que hay una fuente que no existe.
    """
    if "/" in fichero or "\\" in fichero:
        raise HTTPException(404, "No existe esa clase")
    clase = await clases_store.leer(fichero)
    if clase is None:
        raise HTTPException(404, "No existe esa clase")

    registro = ProviderRegistry(get_settings())
    material_examenes = ""
    origen = "solo la clase"
    fuentes: list[dict] = []
    # Lo que ha pasado de verdad con lo que se ha intentado. Se devuelve a
    # la pantalla porque el primer intento se tragaba los fallos en
    # silencio: si el PDF no se podia leer, seguia adelante como si nada y
    # la persona se quedaba sin saber si su fichero se habia usado o no.
    diario: list[str] = []

    # 1. Examenes subidos a mano, si los hay.
    if pdf is not None:
        datos = await pdf.read()
        if not datos:
            diario.append(f"El PDF «{pdf.filename}» llegó vacío.")
        else:
            kb = len(datos) // 1024
            try:
                extraido = await asyncio.to_thread(clases_diapositivas.extraer, datos)
                texto_pdf = extraido["texto"].strip()
                if texto_pdf:
                    material_examenes = texto_pdf[:18000]
                    origen = f"los exámenes que ha subido ({pdf.filename}, {extraido['paginas']} páginas)"
                    diario.append(
                        f"Leído «{pdf.filename}» ({kb} KB, {extraido['paginas']} páginas): "
                        f"{len(texto_pdf)} caracteres de texto, se usan los primeros "
                        f"{len(material_examenes)}."
                    )
                else:
                    # ES UN ESCANEO. Se lee con vision en vez de rendirse:
                    # los examenes de una asignatura casi siempre llegan
                    # asi, y son justo los que mas valen.
                    diario.append(
                        f"«{pdf.filename}» no tiene texto (es un escaneo). "
                        f"Leyéndolo página a página con reconocimiento de imagen…"
                    )
                    leido = await _leer_escaneado(registro, datos, pdf.filename or "examen.pdf")
                    if leido["texto"].strip():
                        material_examenes = leido["texto"][:18000]
                        origen = (
                            f"los exámenes escaneados que ha subido "
                            f"({pdf.filename}, {leido['paginas_leidas']} páginas leídas)"
                        )
                        diario.append(
                            f"Leídas {leido['paginas_leidas']} páginas del escaneo"
                            + (f" (de {leido['paginas_totales']} en total; "
                               f"el resto no se ha mirado para no disparar el gasto)"
                               if leido["paginas_totales"] > leido["paginas_leidas"] else "")
                            + f": {len(leido['texto'])} caracteres."
                        )
                        if leido["fallos"]:
                            diario.append(f"{leido['fallos']} páginas no se pudieron leer.")
                    else:
                        diario.append(
                            "No se ha podido sacar texto del escaneo. "
                            "Puede que la calidad sea muy baja."
                        )
            except Exception as e:
                diario.append(f"No se pudo leer «{pdf.filename}»: {e}")

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

    entrada = "=== LO QUE SE EXPLICO EN CLASE ===\n" + clase[:25000]
    if material_examenes:
        entrada += "\n\n=== PREGUNTAS DE EXAMENES ANTERIORES SOBRE ESTOS TEMAS ===\n" + material_examenes
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
