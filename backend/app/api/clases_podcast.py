"""
LA CLASE, CONVERTIDA EN PODCAST PARA ESCUCHARLA EN EL COCHE.

QUE RESUELVE

Un resumen escrito solo sirve sentado delante de una pantalla. Muchos
ratos muertos -conducir, andar, el gimnasio- son ratos en los que se
podria repasar, pero no se puede leer. Esto convierte el resumen en una
conversacion de dos voces que se escucha como un podcast.

POR QUE UN DIALOGO Y NO UN TEXTO LEIDO

Leer un resumen en voz alta suena a maquina y se desconecta a los dos
minutos: un texto escrito para leerse tiene frases largas, incisos y
enumeraciones que en audio se pierden. Dos personas explicandose las
cosas obliga a repetir lo importante, a preguntar "¿y eso por que?", y
a ir mas despacio en lo dificil. Se retiene mucho mas.

POR QUE UN FICHERO Y NO REPRODUCIRLO EN LA PAGINA

Se penso en leerlo con la voz del propio navegador, que es gratis y no
gasta servidor. No vale para lo que se pide: en el movil, la lectura
del navegador SE CORTA en cuanto se apaga la pantalla o se cambia de
aplicacion. Justo lo que pasa al conducir. Un fichero de audio se
descarga, se abre con el reproductor del movil, suena por el Bluetooth
del coche y sigue con la pantalla apagada.

SOBRE LA VOZ

Se usa edge-tts, que da voces neuronales en español de España -dos
voces distintas, una por persona- gratis y sin clave de API. El
problema: usa un servicio no oficial de Microsoft que de vez en cuando
se cae o bloquea peticiones durante horas seguidas (es un fallo
conocido y documentado del propio proyecto, no algo que se pueda
arreglar desde aqui).

Por eso hay un segundo motor de respaldo: gTTS (la voz de Google
Traductor). Es mucho mas estable, pero solo da una voz por idioma, asi
que si se usa este respaldo el podcast se oye con la misma voz para
las dos personas -se pierde el efecto de dialogo, pero se recupera el
audio en vez de quedarse solo con el guion escrito-.

Si NINGUNO de los dos funciona, se devuelve igualmente el guion
escrito, que ya es util por si solo y ademas se puede pegar en otra
herramienta que lo lea.
"""
from __future__ import annotations

import asyncio
import io
import re
import tempfile
from pathlib import Path

# Dos voces distintas y del mismo pais, para que suene a conversacion y
# no a dos locutores de sitios diferentes. Elvira y Alvaro son las voces
# neuronales de España.
VOZ_A = "es-ES-ElviraNeural"
VOZ_B = "es-ES-AlvaroNeural"

# Tope de caracteres del guion. Un guion muy largo tarda mucho en
# sintetizarse y en el plan gratuito puede agotar el tiempo de la
# peticion. 9000 caracteres son unos 10-12 minutos de audio, que es
# justo lo que dura un trayecto corto.
MAX_CARACTERES_GUION = 9000


INSTRUCCION_GUION = (
    "Eres el guionista de un pódcast educativo en español de España. Te "
    "dan los apuntes de una clase y escribes una conversación entre dos "
    "personas que la repasan en voz alta.\n\n"

    "QUIÉNES SON\n"
    "ANA: lleva la conversación. Va presentando los temas y va cerrando "
    "cada bloque con una frase que resume lo dicho.\n"
    "LUIS: pregunta lo que un estudiante preguntaría, pide ejemplos, y "
    "repite con sus palabras lo que acaba de entender.\n\n"

    "FORMATO OBLIGATORIO. Cada línea empieza por el nombre y dos puntos:\n"
    "ANA: Hoy repasamos la clase de neumología.\n"
    "LUIS: Vale, ¿y por dónde empezamos?\n\n"

    "CÓMO TIENE QUE SONAR\n"
    "- ESTO SE ESCUCHA, NO SE LEE. Frases cortas. Nada de incisos largos "
    "ni de listas con guiones: si hay que enumerar, se dice «tres cosas: "
    "la primera…, la segunda…».\n"
    "- Nada de números de apartado, ni asteriscos, ni símbolos, ni "
    "abreviaturas raras. Escribe «por ciento» en vez de «%», y "
    "«milímetros» en vez de «mm». Se va a leer literal en voz alta.\n"
    "- Cuando aparezca un término técnico, que LUIS pregunte qué es y "
    "ANA lo explique en una frase. Esa es la parte que más se retiene.\n"
    "- Ritmo natural: alguna interjección («ya veo», «vale», «claro»), "
    "pero sin pasarse ni hacerlo tonto.\n\n"

    "ESTRUCTURA\n"
    "1. ANA saluda y dice en una frase de qué va la clase.\n"
    "2. Se repasan los conceptos por orden, del más importante al menos.\n"
    "3. ANA cierra con un repaso rápido de las tres o cuatro ideas que "
    "hay que llevarse.\n\n"

    "LO QUE NO PUEDES HACER\n"
    "- NO te inventes contenido que no esté en los apuntes. Si algo está "
    "poco claro en el material, que ANA lo diga: «esto en clase quedó "
    "poco desarrollado».\n"
    "- NO añadas datos, cifras ni nombres que no aparezcan.\n"
    "- No escribas nada fuera del diálogo: ni títulos, ni acotaciones, "
    "ni indicaciones de sonido. Solo líneas ANA: y LUIS:."
)


def _limpiar_para_voz(t: str) -> str:
    """Quita lo que un sintetizador leería en alto y no debería.

    Los asteriscos del markdown se leen como "asterisco", las almohadillas
    igual, y un guion suelto al principio de linea suena a tropiezo.
    """
    t = re.sub(r"[*_#`]+", "", t)
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def partir_en_turnos(guion: str) -> list[tuple[str, str]]:
    """Convierte el guion en una lista de (voz, texto).

    Si una linea no trae quien habla -porque el modelo se ha saltado el
    formato- se le asigna la misma voz que a la anterior en vez de
    descartarla: perder contenido es peor que un turno mal repartido.
    """
    turnos: list[tuple[str, str]] = []
    voz_actual = VOZ_A
    for linea in _limpiar_para_voz(guion).splitlines():
        linea = linea.strip()
        if not linea:
            continue
        m = re.match(r"^(ANA|LUIS)\s*:\s*(.+)$", linea, re.IGNORECASE)
        if m:
            voz_actual = VOZ_A if m.group(1).upper() == "ANA" else VOZ_B
            texto = m.group(2).strip()
        else:
            texto = linea
        if texto:
            turnos.append((voz_actual, texto))
    return turnos


async def sintetizar(guion: str) -> bytes:
    """Convierte el guion en un mp3, probando dos motores de voz.

    Primero edge-tts, que da dos voces distintas (suena a dialogo de
    verdad) pero depende de un servicio de Microsoft que falla a ratos.
    Si eso falla por cualquier motivo, se cae a gTTS: una sola voz, pero
    mucho mas fiable. Es mejor un podcast con una sola voz que ningun
    podcast.
    """
    turnos = partir_en_turnos(guion)
    if not turnos:
        raise ValueError("El guion no tiene ninguna línea que leer")

    try:
        return await _sintetizar_edge(turnos)
    except Exception:
        return await _sintetizar_gtts(turnos)


async def _sintetizar_edge(turnos: list[tuple[str, str]]) -> bytes:
    """Dos voces neuronales alternando. Se sintetiza turno a turno y se
    concatenan los bytes: los mp3 se pueden pegar uno detras de otro sin
    recodificar, no hace falta abrir ningun editor de audio.
    """
    import edge_tts

    trozos: list[bytes] = []
    for voz, texto in turnos:
        com = edge_tts.Communicate(texto, voz)
        buf = bytearray()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        if buf:
            trozos.append(bytes(buf))

    if not trozos:
        raise ValueError("No se pudo generar audio de ningún turno con edge-tts")
    return b"".join(trozos)


async def _sintetizar_gtts(turnos: list[tuple[str, str]]) -> bytes:
    """Respaldo con la voz de Google Traductor: una sola voz para las
    dos personas, pero mucho mas estable que el servicio de Microsoft.

    gTTS hace una petición de red bloqueante (no es async), así que se
    ejecuta en un hilo aparte para no congelar el resto del servidor
    mientras se genera.
    """
    from gtts import gTTS

    def _turno_a_mp3(texto: str) -> bytes:
        buf = io.BytesIO()
        gTTS(text=texto, lang="es", tld="es").write_to_fp(buf)
        return buf.getvalue()

    trozos: list[bytes] = []
    for _voz, texto in turnos:
        datos = await asyncio.to_thread(_turno_a_mp3, texto)
        if datos:
            trozos.append(datos)

    if not trozos:
        raise ValueError("No se pudo generar audio de ningún turno con gTTS")
    return b"".join(trozos)
