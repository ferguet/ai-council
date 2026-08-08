"""
VALORES DE LABORATORIO: METER LA CIFRA Y QUE TE DIGA SI ES ALTA O BAJA.

EL PROBLEMA QUE RESUELVE

Marcar "anemia" sí o no obliga a haber decidido antes que 10,2 de hemoglobina
es anemia. Y esa es justo la parte que cuesta cuando se empieza: uno tiene la
cifra delante y no sabe de que lado cae, sobre todo en los parametros que
cambian con el sexo o que casi nadie recuerda de memoria.

Aqui se escribe la cifra tal cual sale en el papel y el codigo dice si esta
alta, baja o normal, y a que hallazgo corresponde. Se aprende el rango de
paso, que es lo que de verdad hace falta.

SIN INTELIGENCIA ARTIFICIAL, A PROPOSITO

Un rango de referencia es una tabla, no una opinion. Preguntarselo a un
modelo seria mas lento, costaria dinero y ademas daria respuestas distintas
en dias distintos. Aqui esta escrito, se puede leer, y se puede corregir.

LOS RANGOS SON ORIENTATIVOS

Cada laboratorio tiene los suyos y varian con la edad, el embarazo y el
metodo de medida. Estos son los de adulto que se usan habitualmente, y la
app lo dice en pantalla: sirven para estudiar, no para decidir sobre un
paciente.
"""
from __future__ import annotations

# Cada analito: clave, nombre, unidad, rango normal y a que hallazgo del
# catalogo corresponde cuando esta por encima o por debajo.
#
# `rango` puede ser una pareja (min, max) o un diccionario por sexo cuando de
# verdad cambia -la hemoglobina y el hematocrito, basicamente-. Fingir un
# rango unico ahi seria dar por normal una anemia en un varon.
ANALITOS: list[dict] = [
    # --- Hemograma ---
    {"clave": "hemoglobina", "nombre": "Hemoglobina", "unidad": "g/dL",
     "grupo": "Hemograma", "rango": {"varon": (13.0, 17.0), "mujer": (12.0, 16.0)},
     "bajo": "anemia", "alto": "eritrocitosis"},
    {"clave": "vcm", "nombre": "VCM", "unidad": "fL", "grupo": "Hemograma",
     "rango": (80, 100), "bajo": "microcitosis", "alto": "macrocitosis"},
    {"clave": "leucocitos", "nombre": "Leucocitos", "unidad": "x10⁹/L",
     "grupo": "Hemograma", "rango": (4.0, 11.0),
     "bajo": "leucopenia", "alto": "leucocitosis"},
    {"clave": "neutrofilos", "nombre": "Neutrófilos", "unidad": "x10⁹/L",
     "grupo": "Hemograma", "rango": (1.5, 7.5),
     "bajo": "neutropenia", "alto": "neutrofilia"},
    {"clave": "linfocitos", "nombre": "Linfocitos", "unidad": "x10⁹/L",
     "grupo": "Hemograma", "rango": (1.0, 4.5),
     "bajo": None, "alto": "linfocitosis_absoluta"},
    {"clave": "basofilos", "nombre": "Basófilos", "unidad": "%",
     "grupo": "Hemograma", "rango": (0.0, 1.0), "bajo": None, "alto": "basofilia"},
    {"clave": "plaquetas", "nombre": "Plaquetas", "unidad": "x10⁹/L",
     "grupo": "Hemograma", "rango": (150, 450),
     "bajo": "trombopenia", "alto": "trombocitosis"},

    {"clave": "reticulocitos", "nombre": "Reticulocitos", "unidad": "%",
     "grupo": "Hemograma", "rango": (0.5, 2.0),
     "bajo": "reticulocitos_bajos", "alto": "reticulocitos_altos"},
    {"clave": "hcm", "nombre": "HCM", "unidad": "pg", "grupo": "Hemograma",
     "rango": (27, 33), "bajo": "hipocromia", "alto": None},

    # --- Metabolismo del hierro y vitaminas ---
    {"clave": "ferritina", "nombre": "Ferritina", "unidad": "ng/mL",
     "grupo": "Hierro y vitaminas",
     "rango": {"varon": (30, 400), "mujer": (15, 150)},
     "bajo": "ferritina_baja", "alto": "ferritina_alta"},
    {"clave": "sideremia", "nombre": "Hierro sérico", "unidad": "µg/dL",
     "grupo": "Hierro y vitaminas", "rango": (60, 170),
     "bajo": "sideremia_baja", "alto": None},
    {"clave": "ist", "nombre": "Índice de saturación de transferrina", "unidad": "%",
     "grupo": "Hierro y vitaminas", "rango": (20, 45),
     "bajo": "ist_bajo", "alto": None},
    {"clave": "transferrina", "nombre": "Transferrina", "unidad": "mg/dL",
     "grupo": "Hierro y vitaminas", "rango": (200, 360),
     "bajo": None, "alto": "transferrina_alta"},
    {"clave": "b12", "nombre": "Vitamina B12", "unidad": "pg/mL",
     "grupo": "Hierro y vitaminas", "rango": (200, 900),
     "bajo": "b12_baja", "alto": None},
    {"clave": "folico", "nombre": "Ácido fólico", "unidad": "ng/mL",
     "grupo": "Hierro y vitaminas", "rango": (3, 17),
     "bajo": "folico_bajo", "alto": None},
    {"clave": "haptoglobina", "nombre": "Haptoglobina", "unidad": "mg/dL",
     "grupo": "Hierro y vitaminas", "rango": (30, 200),
     "bajo": "haptoglobina_baja", "alto": None},
    {"clave": "bilirrubina_indirecta", "nombre": "Bilirrubina indirecta", "unidad": "mg/dL",
     "grupo": "Hierro y vitaminas", "rango": (0.1, 0.8),
     "bajo": None, "alto": "bilirrubina_indirecta_alta"},

    # --- Coagulacion ---
    {"clave": "inr", "nombre": "INR", "unidad": "", "grupo": "Coagulación",
     "rango": (0.8, 1.2), "bajo": None, "alto": "tp_alargado"},
    {"clave": "fibrinogeno", "nombre": "Fibrinógeno", "unidad": "mg/dL",
     "grupo": "Coagulación", "rango": (200, 400),
     "bajo": "hipofibrinogenemia", "alto": None},

    {"clave": "ttpa", "nombre": "TTPA", "unidad": "s", "grupo": "Coagulación",
     "rango": (25, 35), "bajo": None, "alto": "ttpa_prolongado"},
    {"clave": "dimero_d", "nombre": "Dímero D", "unidad": "ng/mL", "grupo": "Coagulación",
     "rango": (0, 500), "bajo": None, "alto": "dimero_d_elevado"},

    # --- Inflamacion e infeccion ---
    {"clave": "pcr", "nombre": "PCR", "unidad": "mg/L", "grupo": "Inflamación",
     "rango": (0, 5), "bajo": None, "alto": "pcr_elevada"},
    {"clave": "vsg", "nombre": "VSG", "unidad": "mm/h", "grupo": "Inflamación",
     "rango": (0, 20), "bajo": None, "alto": "vsg_elevada"},
    {"clave": "procalcitonina", "nombre": "Procalcitonina", "unidad": "ng/mL",
     "grupo": "Inflamación", "rango": (0.0, 0.5),
     "bajo": None, "alto": "procalcitonina_elevada"},

    # --- Bioquimica ---
    {"clave": "creatinina", "nombre": "Creatinina", "unidad": "mg/dL",
     "grupo": "Bioquímica", "rango": (0.6, 1.2),
     "bajo": None, "alto": "insuficiencia_renal"},
    {"clave": "ldh", "nombre": "LDH", "unidad": "U/L", "grupo": "Bioquímica",
     "rango": (135, 225), "bajo": None, "alto": "ldh_elevada"},
    {"clave": "got", "nombre": "GOT (AST)", "unidad": "U/L", "grupo": "Bioquímica",
     "rango": (5, 40), "bajo": None, "alto": "transaminasas_elevadas"},
    {"clave": "gpt", "nombre": "GPT (ALT)", "unidad": "U/L", "grupo": "Bioquímica",
     "rango": (5, 40), "bajo": None, "alto": "transaminasas_elevadas"},
    {"clave": "bilirrubina", "nombre": "Bilirrubina total", "unidad": "mg/dL",
     "grupo": "Bioquímica", "rango": (0.2, 1.2), "bajo": None, "alto": "ictericia"},
    {"clave": "albumina", "nombre": "Albúmina", "unidad": "g/dL",
     "grupo": "Bioquímica", "rango": (3.5, 5.0), "bajo": "albumina_baja", "alto": None},
    {"clave": "calcio", "nombre": "Calcio", "unidad": "mg/dL", "grupo": "Bioquímica",
     "rango": (8.5, 10.5), "bajo": "hipocalcemia", "alto": "hipercalcemia"},
    {"clave": "potasio", "nombre": "Potasio", "unidad": "mEq/L", "grupo": "Bioquímica",
     "rango": (3.5, 5.1), "bajo": None, "alto": "hiperpotasemia"},
    {"clave": "fosforo", "nombre": "Fósforo", "unidad": "mg/dL", "grupo": "Bioquímica",
     "rango": (2.5, 4.5), "bajo": None, "alto": "hiperfosfatemia"},
    {"clave": "acido_urico", "nombre": "Ácido úrico", "unidad": "mg/dL",
     "grupo": "Bioquímica", "rango": (3.5, 7.2), "bajo": None, "alto": "acido_urico_elevado"},
    {"clave": "amonio", "nombre": "Amonio", "unidad": "µg/dL", "grupo": "Bioquímica",
     "rango": (15, 45), "bajo": None, "alto": "amoniaco_elevado"},
    {"clave": "ck", "nombre": "CK", "unidad": "U/L", "grupo": "Bioquímica",
     "rango": (30, 200), "bajo": None, "alto": "rabdomiolisis"},
    {"clave": "ph", "nombre": "pH arterial", "unidad": "", "grupo": "Bioquímica",
     "rango": (7.35, 7.45), "bajo": "acidosis_metabolica", "alto": None},
]

ANALITOS_POR_CLAVE = {a["clave"]: a for a in ANALITOS}


def rango_de(analito: dict, sexo: str | None) -> tuple[float, float]:
    """El rango que toca, teniendo en cuenta el sexo si el analito lo distingue."""
    r = analito["rango"]
    if isinstance(r, dict):
        # Sin sexo declarado se coge el rango mas ancho posible: preferimos
        # no llamar anormal a algo que quiza no lo sea.
        if sexo in r:
            return r[sexo]
        minimos = [v[0] for v in r.values()]
        maximos = [v[1] for v in r.values()]
        return (min(minimos), max(maximos))
    return r


def interpretar(clave: str, valor: float, sexo: str | None = None) -> dict | None:
    """
    Dice si esa cifra esta alta, baja o normal, y a que hallazgo lleva.

    Devuelve tambien el rango usado: ver el numero al lado del intervalo es
    la mitad de lo que se aprende aqui.
    """
    a = ANALITOS_POR_CLAVE.get(clave)
    if a is None:
        return None
    lo, hi = rango_de(a, sexo)
    if valor < lo:
        estado, hallazgo = "bajo", a["bajo"]
    elif valor > hi:
        estado, hallazgo = "alto", a["alto"]
    else:
        estado, hallazgo = "normal", None
    return {"clave": clave, "nombre": a["nombre"], "unidad": a["unidad"],
            "valor": valor, "estado": estado, "rango": [lo, hi],
            "hallazgo": hallazgo}


def para_pantalla(sexo: str | None = None) -> list[dict]:
    """La tabla entera con el rango ya resuelto, lista para pintarla."""
    salida = []
    for a in ANALITOS:
        lo, hi = rango_de(a, sexo)
        salida.append({"clave": a["clave"], "nombre": a["nombre"],
                       "unidad": a["unidad"], "grupo": a["grupo"],
                       "rango": [lo, hi], "bajo": a["bajo"], "alto": a["alto"],
                       "depende_sexo": isinstance(a["rango"], dict)})
    return salida
