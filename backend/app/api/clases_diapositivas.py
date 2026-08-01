"""
QUE HA RESALTADO EL PROFESOR EN SUS DIAPOSITIVAS.

LA IDEA

Un PDF no guarda solo las palabras: guarda tambien COMO estan escritas
-tipo de letra, tamaño, color-. Eso permite saber que ha marcado el
profesor como importante sin que nadie tenga que leerse el tema entero.

Se cruza con lo que dijo en clase, y ahi esta el valor de verdad:

  - Lo que el profesor RESALTA en las diapositivas Y ADEMAS explica con
    tiempo en clase, es lo que casi seguro entra.
  - Lo que esta en los apuntes pero no menciona apenas, se puede bajar de
    prioridad y estudiar despues.

Ninguna de las dos señales por separado vale gran cosa. Juntas si.

EL LIMITE, DICHO CLARO

El formato depende del estilo de cada profesor, no de una norma. Habra
quien resalte en rojo lo que de verdad importa, y quien ponga cosas en
mayusculas por costumbre o para separar secciones. Por eso esto NO decide
solo: entrega señales para que las pese la IA junto con la clase, igual
que Vigia en Cuidame nunca decidia con una sola medicion.
"""
from __future__ import annotations

import io
from collections import Counter


def _es_negrita(nombre_fuente: str) -> bool:
    n = (nombre_fuente or "").lower()
    return "bold" in n or "black" in n or "heavy" in n or "semib" in n


def _es_color_llamativo(color) -> bool:
    """
    Rojo o similar. El texto normal es negro o gris muy oscuro, asi que
    cualquier cosa con bastante rojo y poco verde/azul destaca a proposito.
    """
    try:
        if not color:
            return False
        if len(color) == 3:
            r, g, b = color
            return r > 0.45 and g < 0.35 and b < 0.35
        if len(color) == 1:  # escala de grises: nunca es "llamativo"
            return False
    except Exception:
        pass
    return False


def extraer(datos: bytes, max_paginas: int = 120) -> dict:
    """
    Devuelve el texto entero y la lista de trozos resaltados.

    max_paginas existe porque un PDF de 400 diapositivas puede tardar
    muchisimo y agotar la memoria del servidor gratuito. Mejor procesar
    las primeras y decirlo, que morirse a medias sin explicar por que.
    """
    import pdfplumber

    texto_total: list[str] = []
    resaltados: list[str] = []
    tam_por_pagina: list[float] = []

    with pdfplumber.open(io.BytesIO(datos)) as pdf:
        paginas = pdf.pages[:max_paginas]
        recortado = len(pdf.pages) > max_paginas

        for pagina in paginas:
            try:
                texto_total.append(pagina.extract_text() or "")
            except Exception:
                pass

            caracteres = getattr(pagina, "chars", []) or []
            if not caracteres:
                continue

            # El tamaño "normal" de esta pagina es el mas repetido. Se
            # compara contra eso y no contra un numero fijo: cada plantilla
            # de diapositivas usa cuerpos de letra distintos, y un 14 puede
            # ser titulo en una y texto corriente en otra.
            tamaños = Counter(round(c.get("size", 0), 1) for c in caracteres)
            normal = tamaños.most_common(1)[0][0] if tamaños else 0
            tam_por_pagina.append(normal)

            actual, marcado = "", False
            for c in caracteres:
                destaca = (
                    _es_negrita(c.get("fontname", ""))
                    or _es_color_llamativo(c.get("non_stroking_color"))
                    or (normal and round(c.get("size", 0), 1) >= normal * 1.25)
                )
                if destaca:
                    actual += c.get("text", "")
                    marcado = True
                else:
                    if marcado and len(actual.strip()) >= 4:
                        resaltados.append(actual.strip())
                    actual, marcado = "", False
            if marcado and len(actual.strip()) >= 4:
                resaltados.append(actual.strip())

    # Quitar repetidos y basura corta, conservando el orden de aparicion.
    vistos, limpios = set(), []
    for r in resaltados:
        clave = r.lower().strip(" .:,-—")
        if len(clave) < 4 or clave in vistos:
            continue
        vistos.add(clave)
        limpios.append(r.strip())

    return {
        "texto": "\n".join(texto_total),
        "resaltados": limpios[:400],
        "paginas": len(paginas),
        "recortado": recortado,
    }


# Primera pasada: se mira la clase por partes, y de cada parte solo se
# saca lo observado, sin sacar conclusiones todavia. Sacar conclusiones
# viendo un trozo suelto seria decidir con informacion incompleta -algo
# que el profesor solo menciona en la ultima media hora parece irrelevante
# si solo has visto la primera-.
INSTRUCCION_PARTE = (
    "Tienes la lista de lo que el profesor RESALTA en sus diapositivas, y "
    "un TROZO de lo que dijo en clase. Tu tarea es solo observar, sin "
    "concluir nada todavia.\n\n"
    "Devuelve una lista corta con:\n"
    "- Que conceptos de la lista de resaltados aparecen en este trozo, y si "
    "el profesor los explica de pasada o se detiene en ellos.\n"
    "- Que conceptos repite o insiste en este trozo AUNQUE no esten en la "
    "lista de resaltados.\n"
    "- Si dice expresamente que algo no entra o no lo va a preguntar.\n\n"
    "Se breve: una linea por concepto. No inventes nada que no este en el "
    "texto. Si en este trozo no aparece ninguno de los conceptos "
    "resaltados, dilo en una linea y ya esta."
)


INSTRUCCION_CRUCE = (
    "Tienes lo que el profesor RESALTA en sus diapositivas, y las "
    "observaciones recogidas al recorrer su clase por partes.\n\n"
    "Cruza las dos y devuelve una GUIA DE PRIORIDADES para estudiar, en tres "
    "apartados y en este orden:\n\n"
    "1. MUY PROBABLE QUE ENTRE — conceptos que el profesor resalta en las "
    "diapositivas Y ADEMAS explica, repite o dedica tiempo en clase. Es la "
    "coincidencia de las dos señales lo que los pone aqui: dilo en una linea "
    "por concepto, explicando brevemente por que.\n\n"
    "2. IMPORTANTE PERO MENOS — aparece solo en una de las dos: o lo resalta "
    "en las diapositivas pero apenas lo menciona, o lo explica en clase pero "
    "no lo destaca en los apuntes.\n\n"
    "3. SE PUEDE DEJAR PARA EL FINAL — esta en las diapositivas pero el "
    "profesor no lo menciona practicamente nada, o dijo expresamente que no "
    "entra.\n\n"
    "REGLAS IMPORTANTES:\n"
    "- No inventes conceptos que no esten en ninguno de los dos textos.\n"
    "- El formato de las diapositivas es una PISTA, no una prueba: hay "
    "profesores que ponen cosas en negrita por costumbre. Si algo esta "
    "resaltado pero no lo menciona nunca en clase, no lo pongas en el primer "
    "apartado.\n"
    "- Si algo aparece muy repetido en la clase, dilo aunque no este "
    "resaltado: la insistencia del profesor pesa mas que el formato.\n"
    "- Termina con una linea honesta diciendo que esto es una orientacion "
    "basada en lo que el profesor enfatizo, no una prediccion segura del "
    "examen."
)
