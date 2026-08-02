"""
PLANTILLAS FIJAS DE LOS DOCUMENTOS POLICIALES.

POR QUE ESTO NO LO ESCRIBE LA IA.

Todo lo que hay en este fichero es texto LITERAL que se inserta tal
cual. Ni una coma la decide el modelo. El motivo es concreto: entre
estas plantillas esta la advertencia legal que se le lee al denunciante
-obligacion de decir verdad, articulos 433 LECrim y 456/457/458 CP-.

Un modelo de lenguaje, si le dejas escribir eso, tiende a "mejorarlo":
lo resume, cambia una palabra, cita mal un articulo. Y una advertencia
legal mal transcrita en un atestado no es una errata, es un defecto del
documento que puede discutirse despues. Asi que el reparto es tajante:

  - Formulas legales y estructura -> de aqui, literal.
  - Relato de los hechos          -> eso si lo redacta la IA.

CON DATOS FICTICIOS. Esta herramienta se ha construido para trabajar
con casos inventados. Antes de usarla con datos reales de personas hace
falta resolver donde se procesan esos datos (ver policia.py).
"""
from __future__ import annotations

# ---------------------------------------------------------------------
# ADVERTENCIA LEGAL AL DENUNCIANTE
#
# Literal, tomada de un documento real. No se toca.
# ---------------------------------------------------------------------
ADVERTENCIA_DENUNCIANTE = (
    "-- Que ha sido previamente informado/a de la obligación legal que tiene "
    "de decir la verdad (art.433 de L.E.Crim.), de la posible responsabilidad "
    "penal en la que puede incurrir en caso de acusar o imputar falsamente a "
    "una persona una infracción penal (art. 456 de C.P.), simular ser "
    "responsable o víctima de una infracción penal, denunciar una infracción "
    "penal falsa o inexistente (art.457 de C.P.), o faltar a la verdad en su "
    "testimonio (art.458 de C.P.).\n\n"
    "-- Que una vez informado/a de lo anteriormente expuesto, MANIFIESTA:"
)

CIERRE_DENUNCIA = (
    "-- Que no tiene nada más que manifestar por lo que una vez leída, firma "
    "la presente en prueba de conformidad, en unión del resto de personas "
    "intervinientes si las hubiere y de la Instrucción reseñada.\n\n"
    "-- CONSTE Y CERTIFICO."
)

CIERRE_COMPARECENCIA = (
    "-- Que no teniendo nada más que manifestar, se da por terminada la "
    "presente comparecencia, que firman los funcionarios actuantes en unión "
    "de la Instrucción reseñada.\n\n"
    "-- CONSTE Y CERTIFICO."
)


def cabecera_denuncia(localidad: str, hora: str, minutos: str, dia: str,
                      mes: str, anio: str) -> str:
    """La formula de apertura, con los huecos que rellena el usuario.

    Los datos van en el formulario a proposito: la hora y el lugar de
    una diligencia no son cosa que deba deducir un modelo de un audio.
    """
    return (
        f"-- En {localidad}, siendo las {hora} horas {minutos} minutos del "
        f"día {dia} de {mes} de {anio}, ante la Instrucción arriba reseñada."
    )


def cabecera_comparecencia(localidad: str, hora: str, minutos: str, dia: str,
                           mes: str, anio: str, agentes: str) -> str:
    return (
        f"-- En {localidad}, siendo las {hora} horas {minutos} minutos del "
        f"día {dia} de {mes} de {anio}, ante la Instrucción arriba reseñada.\n\n"
        f"-- COMPARECEN: Los funcionarios del Cuerpo Nacional de Policía con "
        f"carné profesional número {agentes}, quienes en relación con los "
        f"hechos que se investigan, MANIFIESTAN:"
    )


# ---------------------------------------------------------------------
# CAMPOS QUE PIDE CADA DOCUMENTO
#
# Se piden en un formulario y se insertan tal cual. NUNCA salen del
# audio: una hora o un numero de atestado deducidos de una grabacion
# son justo el tipo de dato que un modelo rellena "razonablemente" y
# se inventa.
# ---------------------------------------------------------------------
CAMPOS = {
    "parte": [
        ("localidad", "Municipio", "ALCAZAR DE SAN JUAN"),
        ("indicativo", "Indicativo", "Z-81"),
        ("agentes", "Agentes (carné profesional)", ""),
        ("origen", "Origen de la actuación", "A requerimiento de ciudadano"),
    ],
    "denuncia": [
        ("localidad", "Localidad", "Alcazar de san juan"),
        ("hora", "Hora", ""),
        ("minutos", "Minutos", ""),
        ("dia", "Día", ""),
        ("mes", "Mes", ""),
        ("anio", "Año", "2026"),
    ],
    "comparecencia": [
        ("localidad", "Localidad", "Alcazar de san juan"),
        ("hora", "Hora", ""),
        ("minutos", "Minutos", ""),
        ("dia", "Día", ""),
        ("mes", "Mes", ""),
        ("anio", "Año", "2026"),
        ("agentes", "Carné/s profesional/es", ""),
    ],
}

# Origenes de actuacion vistos en documentos reales. Lista abierta: si
# falta alguno se puede escribir a mano, porque una lista cerrada mal
# hecha obliga a elegir algo falso.
ORIGENES = [
    "A requerimiento de ciudadano",
    "Por indicación de la Sala C-80",
    "De oficio",
    "En servicio de prevención",
    "A requerimiento de otro Cuerpo policial",
]
