"""
LEER EXAMENES ESCANEADOS (PDF QUE SON FOTOS, NO TEXTO).

EL PROBLEMA REAL

Los examenes de una asignatura casi nunca circulan como texto: circulan
como fotocopias escaneadas, o fotos del papel. Para un ordenador eso no
es un documento, es una imagen: no hay ni una letra que extraer.

Y es justo el caso que mas importa. Los del MIR estan publicados en texto
y se encuentran en internet; los de la asignatura concreta, que son los
que de verdad predicen lo que va a caer, son los que llegan escaneados.
Rechazarlos era dejar fuera la fuente mas valiosa.

COMO SE RESUELVE

Se convierte cada pagina en una imagen y se le pide a un modelo con
vision que transcriba lo que ve. No es OCR clasico (Tesseract y compañia,
que ademas exigen instalar programas que Render no tiene): es leer la
foto y escribir el texto, que con examenes maquetados a dos columnas y
tablas funciona bastante mejor.

LOS LIMITES, DICHOS ANTES DE QUE MOLESTEN

- Cada pagina es una llamada a la IA, asi que un examen de 30 paginas
  cuesta 30 llamadas. Se pone un tope y se avisa de cuantas se han hecho.
- Leer una foto nunca es exacto al cien por cien. Estos textos valen para
  saber QUE se pregunta y COMO, que es para lo que se usan aqui; no
  valdrian para copiar una cifra al pie de la letra.
"""
from __future__ import annotations

import asyncio
import base64

# Tope de paginas. Un examen tipico son 10-20 paginas; mas alla de esto
# casi seguro es otra cosa (un temario entero) y no compensa el gasto.
MAX_PAGINAS = 20

INSTRUCCION_OCR = (
    "Esta imagen es la pagina de un examen. Transcribe TODO el texto que "
    "veas, respetando el orden de lectura y numerando las preguntas como "
    "aparezcan. Incluye las opciones de respuesta (a, b, c, d) y, si esta "
    "marcada o indicada la correcta, dilo.\n\n"
    "No resumas, no interpretes y no añadas nada que no este escrito. Si "
    "una parte no se lee bien, escribe [ilegible] en ese punto en vez de "
    "adivinar: en un examen, una palabra inventada cambia la pregunta."
)


def paginas_como_imagenes(datos: bytes, maximo: int = MAX_PAGINAS) -> list[str]:
    """Cada pagina del PDF en PNG codificado en base64."""
    import fitz  # pymupdf

    imagenes: list[str] = []
    doc = fitz.open(stream=datos, filetype="pdf")
    try:
        for i, pagina in enumerate(doc):
            if i >= maximo:
                break
            # 150 ppp: suficiente para leer letra de examen sin que la
            # imagen se dispare de tamaño (y por tanto de coste).
            pix = pagina.get_pixmap(dpi=150)
            imagenes.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    finally:
        doc.close()
    return imagenes


async def imagenes_en_hilo(datos: bytes, maximo: int = MAX_PAGINAS) -> list[str]:
    """Rasterizar bloquea; se saca del hilo principal."""
    return await asyncio.to_thread(paginas_como_imagenes, datos, maximo)
