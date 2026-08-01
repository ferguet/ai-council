"""
PARTIR LAS CLASES LARGAS PARA PODER TRANSCRIBIRLAS ENTERAS.

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
"""
from __future__ import annotations

import asyncio
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
        destino = carpeta / f"trozo_{n:03d}{ruta.suffix or '.m4a'}"
        desde = max(0.0, inicio - (SEGUNDOS_DE_SOLAPE if n > 1 else 0))
        try:
            subprocess.run(
                [
                    _ffmpeg(), "-y", "-loglevel", "error",
                    "-ss", str(desde), "-t", str(paso + SEGUNDOS_DE_SOLAPE),
                    "-i", str(ruta), "-c", "copy", str(destino),
                ],
                capture_output=True, timeout=300, check=True,
            )
            if destino.exists() and destino.stat().st_size > 1000:
                trozos.append(destino)
        except Exception:
            # Si "-c copy" no vale para este formato, se reintenta
            # recodificando a algo que Whisper entiende seguro.
            try:
                destino = carpeta / f"trozo_{n:03d}.m4a"
                subprocess.run(
                    [
                        _ffmpeg(), "-y", "-loglevel", "error",
                        "-ss", str(desde), "-t", str(paso + SEGUNDOS_DE_SOLAPE),
                        "-i", str(ruta), "-ac", "1", "-ar", "16000",
                        "-b:a", "48k", str(destino),
                    ],
                    capture_output=True, timeout=300, check=True,
                )
                if destino.exists() and destino.stat().st_size > 1000:
                    trozos.append(destino)
            except Exception:
                pass
        inicio += paso

    return trozos or [ruta]


async def partir_en_hilo(ruta: Path, carpeta: Path) -> list[Path]:
    """ffmpeg bloquea; se saca del hilo principal para no congelar el servidor."""
    return await asyncio.to_thread(partir, ruta, carpeta)


def carpeta_temporal() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="clase_")
