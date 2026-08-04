"""
PREPARAR EL AUDIO PARA QUE SE PUEDA TRANSCRIBIR DE VERDAD.

LO PRIMERO DE TODO: NORMALIZAR

Todo audio que entra se recodifica antes de nada (ver `normalizar`). Lo
que graba el navegador en el movil viene sin duracion en la cabecera, y
eso hace que Whisper no lo lea bien y devuelva "gracias por ver el
video" repetido en vez de avisar de que no ha entendido nada. Esa es la
correccion mas importante de este fichero.

DESPUES: PARTIR LAS CLASES LARGAS

EL PROBLEMA

La API de Whisper no acepta ficheros de mas de 25 MB. Una clase de una
hora larga, o cualquier audio traido de otra grabadora con buena calidad,
se pasa de ahi. Hasta ahora la app decia "pesa demasiado, pártalo usted",
que es cargarle a la persona un trabajo que puede hacer la maquina, y
ademas justo el dia que mas falta hace tener la clase transcrita.

Comprimir mas no es la solucion: se pierde inteligibilidad del habla y la
transcripcion empeora. Lo correcto es partir, transcribir cada trozo y
unir el texto.

COMO

Con ffmpeg, que llega dentro del paquete imageio-ffmpeg (no hace falta
que el sistema lo tenga instalado; en Render no lo tiene). Se corta por
TIEMPO, no por bytes: cortar un fichero de audio por la mitad a lo bruto
no da dos audios, da uno roto y basura.

Se copia el flujo tal cual (-c copy) siempre que se puede, asi que cortar
es casi instantaneo y no vuelve a comprimir nada.

EL SOLAPE

Cada trozo se toma con unos segundos de margen sobre el anterior. Sin
eso, un corte puede caer justo en mitad de una palabra y esa palabra se
pierde en los dos lados. Con el solape, la palabra aparece entera en al
menos uno de los dos trozos. A cambio puede repetirse alguna frase en la
union, que es un problema mucho menor que perder contenido.

CUANDO EL CORTE SALE ROTO

"-c copy" es casi instantaneo porque no recodifica: copia los bytes tal
cual. El problema es que a veces "funciona" -ffmpeg sale sin error- y el
trozo resultante esta igualmente dañado, porque el corte no ha caido en
un punto limpio del audio para ese formato. Whisper no avisa de esto: se
traga el trozo roto y devuelve texto de todos modos, normalmente una
frase corta repetida sin sentido ("gracias", "suscribete"...) porque asi
es como se comporta el modelo cuando no reconoce nada real. Por eso cada
trozo se comprueba DESPUES de cortarlo: si su duracion real no se parece
a la pedida, se descarta y se repite recodificando de cero (mas lento,
pero fiable).

CUANDO EL AUDIO ORIGINAL ES BUENO Y AUN ASI SALE MAL

Si ademas del corte se comprueba que el texto final tiene muy pocas
palabras distintas para lo que ha durado el audio, es la misma familia
de fallo pero en el servicio de transcripcion en si, no en el corte de
aqui. Por eso `transcripcion_sospechosa()` vive en este mismo fichero:
las dos comprobaciones abordan la misma alucinacion desde los dos sitios
donde puede colarse.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
from pathlib import Path

# Trozos de 10 minutos: a la calidad que graba la app son unos 4 MB, muy
# por debajo del limite de 25, con margen de sobra para audios traidos de
# fuera que vengan con mejor calidad (y por tanto mas peso por minuto).
MINUTOS_POR_TROZO = 10
SEGUNDOS_DE_SOLAPE = 3


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def normalizar(ruta: Path, carpeta: Path) -> Path:
    """Reescribe el audio a un fichero limpio antes de tocarlo para nada.

    ESTA ES LA CAUSA DEL FAMOSO "gracias por ver el video" x100.

    El navegador graba con MediaRecorder, y lo que sale de ahi es un webm
    "de streaming": se va escribiendo mientras se graba, asi que la
    cabecera se cierra sin saber cuanto va a durar. Resultado: el fichero
    dice que dura "N/A". Comprobado con ffmpeg, un webm normal informa de
    "Duration: 00:00:30.01" y uno recien salido del navegador informa de
    "Duration: N/A".

    Eso rompe dos cosas a la vez, y en silencio:

    1. Aqui, `_duracion_segundos` devolvia None, asi que `partir` se
       rendia y mandaba el audio entero sin trocear.
    2. Y peor: al otro lado, Whisper no consigue recorrer bien un
       contenedor asi, se encuentra con lo que interpreta como silencio,
       y RELLENA. Whisper se entreno con montañas de video, asi que
       cuando no reconoce nada escupe despedidas de YouTube: "gracias por
       ver el video", una y otra vez. No es que entienda mal lo dictado:
       es que no esta oyendo nada y no lo dice.

    La solucion es recodificar SIEMPRE antes de nada. Cuesta unos
    segundos de CPU y a cambio el fichero pasa a tener cabecera correcta,
    duracion real y un formato que Whisper decodifica seguro. Ademas se
    baja a mono y 16 kHz, que es exactamente lo que Whisper usa por
    dentro: no se pierde nada de calidad util y el fichero pesa bastante
    menos, con lo que caben trozos mas largos por debajo del limite.

    Si la recodificacion falla, se devuelve el original: es mejor
    intentar transcribir algo imperfecto que no intentarlo.
    """
    destino = carpeta / "normalizado.m4a"
    try:
        subprocess.run(
            [
                _ffmpeg(), "-y", "-loglevel", "error",
                "-i", str(ruta),
                "-vn",                 # por si el fichero trae video, fuera
                "-ac", "1",            # mono
                "-ar", "16000",        # 16 kHz, lo que Whisper usa
                "-b:a", "48k",
                str(destino),
            ],
            capture_output=True, timeout=900, check=True,
        )
        if destino.exists() and destino.stat().st_size > 1000:
            return destino
    except Exception:
        pass
    return ruta


async def normalizar_en_hilo(ruta: Path, carpeta: Path) -> Path:
    """ffmpeg bloquea; fuera del hilo principal."""
    return await asyncio.to_thread(normalizar, ruta, carpeta)


def _duracion_segundos(ruta: Path) -> float | None:
    """Cuanto dura el audio. None si no se puede averiguar."""
    try:
        salida = subprocess.run(
            [_ffmpeg(), "-i", str(ruta)],
            capture_output=True, text=True, timeout=60,
        ).stderr
        # ffmpeg escribe "Duration: 01:23:45.67" en su salida de error
        for linea in salida.splitlines():
            if "Duration:" in linea:
                trozo = linea.split("Duration:")[1].split(",")[0].strip()
                h, m, s = trozo.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return None


def _cortar(ruta: Path, carpeta: Path, n: int, desde: float, duracion: float,
            copiar: bool) -> Path | None:
    """Un solo intento de corte. None si ffmpeg falla o el resultado es
    demasiado pequeño para ser audio de verdad."""
    destino = carpeta / (f"trozo_{n:03d}{ruta.suffix or '.m4a'}" if copiar
                          else f"trozo_{n:03d}_r.m4a")
    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-ss", str(desde), "-t", str(duracion), "-i", str(ruta)]
    cmd += ["-c", "copy"] if copiar else ["-ac", "1", "-ar", "16000", "-b:a", "48k"]
    cmd += [str(destino)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        if destino.exists() and destino.stat().st_size > 1000:
            return destino
    except Exception:
        pass
    return None


def _corte_valido(destino: Path, duracion_esperada: float) -> bool:
    """"-c copy" puede salir sin error y aun asi dar un trozo roto -corta
    en un punto que ese formato no admite y el audio queda inservible-.
    Se comprueba que lo que ha salido dura lo que tenia que durar; un
    trozo mucho mas corto de lo pedido es la señal de que algo se rompio,
    aunque ffmpeg no haya avisado.
    """
    real = _duracion_segundos(destino)
    if real is None:
        return False
    return real >= max(2.0, duracion_esperada * 0.6)


def partir(ruta: Path, carpeta: Path) -> list[Path]:
    """
    Devuelve la lista de trozos, en orden. Si el audio es corto o no se
    puede partir, devuelve el fichero original solo: mejor intentar
    transcribirlo entero que fallar sin intentarlo.
    """
    duracion = _duracion_segundos(ruta)
    if duracion is None or duracion <= MINUTOS_POR_TROZO * 60:
        return [ruta]

    trozos: list[Path] = []
    paso = MINUTOS_POR_TROZO * 60
    inicio = 0.0
    n = 0
    while inicio < duracion:
        n += 1
        desde = max(0.0, inicio - (SEGUNDOS_DE_SOLAPE if n > 1 else 0))
        duracion_pedida = paso + SEGUNDOS_DE_SOLAPE
        duracion_esperada = min(duracion_pedida, duracion - desde)

        destino = _cortar(ruta, carpeta, n, desde, duracion_pedida, copiar=True)
        if destino is None or not _corte_valido(destino, duracion_esperada):
            # El copy rapido no ha dado un trozo fiable: se repite
            # recodificando de cero, mas lento pero seguro.
            destino = _cortar(ruta, carpeta, n, desde, duracion_pedida, copiar=False)

        if destino is not None:
            trozos.append(destino)
        inicio += paso

    return trozos or [ruta]


async def partir_en_hilo(ruta: Path, carpeta: Path) -> list[Path]:
    """ffmpeg bloquea; se saca del hilo principal para no congelar el servidor."""
    return await asyncio.to_thread(partir, ruta, carpeta)


async def duracion_en_hilo(ruta: Path) -> float | None:
    """Duración del audio original, para poder juzgar despues si el texto
    que ha vuelto de la transcripcion tiene sentido para lo que ha durado.
    """
    return await asyncio.to_thread(_duracion_segundos, ruta)


def carpeta_temporal() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="clase_")


_TIPOS = {
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".webm": "audio/webm", ".ogg": "audio/ogg",
    ".opus": "audio/ogg", ".flac": "audio/flac",
}


def tipo_mime(ruta: Path) -> str:
    """El tipo real del fichero que se va a mandar.

    Importa porque despues de normalizar el fichero ya no es el que
    subio el navegador: seguir anunciando "audio/webm" cuando en realidad
    va un m4a es justo el tipo de detalle que hace que el decodificador
    del otro lado se lie.
    """
    return _TIPOS.get(ruta.suffix.lower(), "audio/mp4")


# Frases con las que Whisper suele "rellenar" cuando no reconoce nada
# real -viene de haberse entrenado con muchisimo video de YouTube, asi
# que en silencio o audio irreconocible tira de despedidas de video-.
_FRASES_HUECAS = (
    "gracias", "suscribete", "suscríbete", "subtitulos", "subtítulos",
    "amara.org", "hasta la proxima", "hasta la próxima",
    "nos vemos en el proximo video", "nos vemos en el próximo video",
)

# Un dictado o una clase hablada normal ronda 90-160 palabras por minuto,
# incluso con pausas para pensar. Por debajo de esto durante varios
# minutos seguidos, lo mas probable es que el audio no se haya
# convertido en texto de verdad.
_PALABRAS_POR_MINUTO_MINIMO = 12


def transcripcion_sospechosa(texto: str, duracion_segundos: float | None) -> str | None:
    """Aviso en texto si la transcripcion tiene toda la pinta de ser un
    fallo -alucinacion sobre audio que no se ha entendido- en vez de
    contenido real. None si parece normal.

    No hay forma de estar seguro sin que una persona lo lea, asi que esto
    no reemplaza la revision: solo evita que un fallo evidente pase
    desapercibido y acabe redactado como si fuera de verdad.
    """
    limpio = re.sub(r"[^\wáéíóúñü\s]", " ", texto.lower(), flags=re.UNICODE)
    palabras = limpio.split()
    if not palabras:
        return None

    unicas = set(palabras)
    machacona = len(palabras) >= 6 and (len(unicas) / len(palabras)) < 0.15
    hueca = any(f in limpio for f in _FRASES_HUECAS) and len(unicas) < 8

    poca_densidad = False
    if duracion_segundos and duracion_segundos > 90:
        minutos = duracion_segundos / 60
        poca_densidad = (len(palabras) / minutos) < _PALABRAS_POR_MINUTO_MINIMO

    if machacona or hueca or poca_densidad:
        return (
            "Esto no tiene pinta de ser una transcripción real: parece que el "
            "transcriptor no ha entendido el audio y ha rellenado con una frase "
            "repetida. El audio grabado sigue a salvo en el dispositivo. Antes de "
            "seguir: escuche esa grabación; si ahí se le oye bien, puede ser un "
            "fallo puntual del servicio y merece la pena intentarlo de nuevo; si "
            "suena mal, esta vez habrá que redactarlo a mano."
        )
    return None
