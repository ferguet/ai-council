"""
CATALOGO DE HALLAZGOS Y BASE DE PATOLOGIAS.

POR QUE UNA LISTA CERRADA Y NO TEXTO LIBRE

Podria dejarse escribir "le duele mucho la cabeza de repente" y que la app
lo interpretara. Es mas comodo de teclear, y es una mala idea: cada
interpretacion es una ocasion de equivocarse en silencio. Si el motor
entiende mal un dato, no avisa de nada -simplemente ordena mal el
diferencial, y el alumno aprende algo falso sin enterarse-.

Con una lista cerrada, el hallazgo que se elige es EXACTAMENTE el mismo
identificador que aparece en la ficha de la patologia. No hay nada que
adivinar y el descarte es fiable. La comodidad se recupera con un buscador
encima de la lista, que es un problema de pantalla y no de fiabilidad.

SOBRE ESTA BASE

El catalogo de hallazgos de abajo es la version de arranque, orientada a los
tres sistemas con los que empieza la app: neurologia, oncohematologia e
infecciosas. Se amplia añadiendo entradas; no hay que tocar el motor.

Las patologias que hay ahora mismo son POCAS y estan aqui para probar que el
razonamiento funciona. NO son la base definitiva ni estan revisadas para
estudiar con ellas. La base real se genera aparte y se valida una por una
antes de entrar.
"""
from __future__ import annotations

SISTEMAS = {
    "neuro": "Neurología",
    "infecciosas": "Infecciosas",
    "oncohemato": "Oncohematología",
}

# ---------------------------------------------------------------------------
# CATALOGO DE HALLAZGOS
# ---------------------------------------------------------------------------
# Agrupado en bloques porque una lista de noventa cosas seguidas no hay quien
# la use en un movil. El buscador de la pantalla filtra sobre el nombre.

HALLAZGOS: list[dict] = []

# COSTE de averiguar cada cosa. No es dinero: es lo que le cuesta al paciente
# y al sistema. Preguntar si tiene fiebre es gratis; una puncion lumbar no.
#
# Sirve para que la app no sugiera empezar la casa por el tejado. Sin esto
# proponia "mira el LCR" como primera pregunta ante una cefalea, que
# discrimina muchisimo pero es exactamente lo que un medico NO hace primero.
COSTES = {
    "Generales": 1,
    "Curso": 1,
    "Neurológicos": 1,
    "Infecciosos": 1,
    "Antecedentes y riesgo": 1,
    "Exploración": 2,
    "Analítica": 4,
    "Imagen": 6,
    "Líquido cefalorraquídeo": 8,
}


def _bloque(bloque: str, items: dict[str, str]) -> None:
    for hid, nombre in items.items():
        HALLAZGOS.append({"id": hid, "nombre": nombre, "bloque": bloque,
                          "coste": COSTES.get(bloque, 1)})


_bloque("Generales", {
    "fiebre": "Fiebre (>38 ºC)",
    "febricula": "Febrícula",
    "perdida_peso": "Pérdida de peso involuntaria",
    "sudoracion_nocturna": "Sudoración nocturna",
    "astenia": "Astenia",
    "anorexia": "Anorexia",
    "malestar_general": "Malestar general",
    "prurito": "Prurito generalizado",
})

_bloque("Curso", {
    "instauracion_subita": "Instauración súbita (segundos)",
    "instauracion_horas": "Instauración en horas",
    "instauracion_dias": "Instauración en días",
    "instauracion_semanas": "Instauración en semanas o meses",
    "curso_recurrente": "Episodios recurrentes previos",
    "curso_progresivo": "Curso progresivo sin mejoría",
})

_bloque("Neurológicos", {
    "cefalea_brusca": "Cefalea de inicio brusco (en trueno)",
    "cefalea_progresiva": "Cefalea progresiva",
    "cefalea_matutina": "Cefalea matutina que despierta",
    "rigidez_nuca": "Rigidez de nuca",
    "signos_meningeos": "Signos meníngeos (Kernig / Brudzinski)",
    "fotofobia": "Fotofobia",
    "vomitos_proyectivos": "Vómitos en escopetazo",
    "alteracion_conciencia": "Alteración del nivel de conciencia",
    "confusion": "Confusión / desorientación",
    "focalidad_motora": "Focalidad motora",
    "deficit_sensitivo": "Déficit sensitivo",
    "afasia": "Afasia",
    "crisis_convulsiva": "Crisis convulsiva",
    "diplopia": "Diplopía",
    "ataxia": "Ataxia",
    "papiledema": "Papiledema",
    "aura_visual": "Aura visual previa",
    "alteracion_conducta": "Alteración de la conducta o del comportamiento",
})

_bloque("Infecciosos", {
    "odinofagia": "Odinofagia",
    "tos": "Tos",
    "expectoracion": "Expectoración purulenta",
    "disnea": "Disnea",
    "dolor_pleuritico": "Dolor pleurítico",
    "diarrea": "Diarrea",
    "disuria": "Disuria / síndrome miccional",
    "exantema": "Exantema",
    "petequias": "Petequias / púrpura",
    "foco_orl": "Foco ORL (otitis, sinusitis)",
    "viaje_reciente": "Viaje reciente a zona endémica",
    "contacto_epidemico": "Contacto epidemiológico conocido",
    "hemoptisis": "Hemoptisis",
})

_bloque("Exploración", {
    "adenopatias_dolorosas": "Adenopatías dolorosas",
    "adenopatias_indoloras": "Adenopatías indoloras y duras",
    "adenopatias_generalizadas": "Adenopatías generalizadas",
    "esplenomegalia": "Esplenomegalia",
    "hepatomegalia": "Hepatomegalia",
    "palidez": "Palidez mucocutánea",
    "equimosis": "Equimosis / hematomas espontáneos",
    "sangrado_mucosas": "Sangrado de mucosas (gingivorragia, epistaxis)",
    "dolor_oseo": "Dolor óseo",
    "masa_palpable": "Masa palpable",
    "hipertrofia_gingival": "Hipertrofia gingival",
})

_bloque("Analítica", {
    "leucocitosis": "Leucocitosis",
    "leucopenia": "Leucopenia",
    "neutrofilia": "Neutrofilia",
    "linfocitosis": "Linfocitosis con linfocitos atípicos",
    "anemia": "Anemia",
    "trombopenia": "Trombopenia",
    "pancitopenia": "Pancitopenia",
    "blastos_sangre": "Blastos en sangre periférica",
    "vsg_elevada": "VSG elevada",
    "pcr_elevada": "PCR elevada",
    "procalcitonina_elevada": "Procalcitonina elevada",
    "ldh_elevada": "LDH elevada",
    "hipercalcemia": "Hipercalcemia",
    "acido_urico_elevado": "Ácido úrico elevado",
})

_bloque("Líquido cefalorraquídeo", {
    "lcr_purulento": "LCR de aspecto turbio o purulento",
    "lcr_claro": "LCR claro",
    "lcr_pleocitosis_pmn": "LCR con pleocitosis de polimorfonucleares",
    "lcr_pleocitosis_linfo": "LCR con pleocitosis linfocitaria",
    "lcr_hipoglucorraquia": "LCR con glucosa baja",
    "lcr_proteinorraquia": "LCR con proteínas elevadas",
    "lcr_hematico": "LCR hemático / xantocrómico",
    "lcr_normal": "LCR normal",
})

_bloque("Imagen", {
    "tc_normal": "TC craneal normal",
    "tc_hemorragia_subaracnoidea": "TC con sangre en espacio subaracnoideo",
    "tc_lesion_ocupante": "TC/RM con lesión ocupante de espacio",
    "rm_temporal": "RM con afectación de lóbulos temporales",
    "rx_condensacion": "Radiografía con condensación pulmonar",
    "masa_mediastinica": "Masa mediastínica",
    "rx_cavitacion_apical": "Radiografía con cavitación apical",
})

_bloque("Antecedentes y riesgo", {
    "inmunodepresion": "Inmunodepresión",
    "vih": "Infección por VIH",
    "esplenectomia": "Esplenectomía previa",
    "quimioterapia_previa": "Quimioterapia o radioterapia previa",
    "antecedente_familiar_onco": "Antecedentes familiares oncológicos",
    "tabaquismo": "Tabaquismo",
    "advp": "Uso de drogas por vía parenteral",
    "sindrome_down": "Síndrome de Down",
    "anticoagulacion": "Tratamiento anticoagulante",
})

HALLAZGOS_POR_ID = {h["id"]: h for h in HALLAZGOS}


def bloques() -> list[dict]:
    """El catalogo agrupado, tal y como lo necesita la pantalla."""
    orden: list[str] = []
    grupos: dict[str, list[dict]] = {}
    for h in HALLAZGOS:
        if h["bloque"] not in grupos:
            grupos[h["bloque"]] = []
            orden.append(h["bloque"])
        grupos[h["bloque"]].append({"id": h["id"], "nombre": h["nombre"]})
    return [{"bloque": b, "hallazgos": grupos[b]} for b in orden]


# ---------------------------------------------------------------------------
# PATOLOGIAS
# ---------------------------------------------------------------------------
# PROVISIONAL. Estas fichas existen para comprobar que el motor descarta y
# ordena como debe. No estan revisadas para estudiar con ellas.
#
# Formato de cada ficha:
#   id, nombre, sistemas, edad_tipica [min, max], sexo, genetica
#   hallazgos: {id_hallazgo: tipico | frecuente | posible | atipico | incompatible}
#
# Los campos explicativos (por que da esta clinica, por que se pide esta
# prueba, que esperamos ver, tratamiento y que esperamos de el, efectos
# secundarios) NO van aqui: se generan una vez con IA sobre esta ficha como
# referencia y se guardan. Ver seccion 6 del proyecto.

PATOLOGIAS: list[dict] = [
    {
        "id": "meningitis_bacteriana",
        "nombre": "Meningitis bacteriana aguda",
        "sistemas": ["infecciosas", "neuro"],
        "edad_tipica": [0, 90],
        "sexo": None,
        "genetica": "Déficit de complemento y asplenia predisponen a meningococo.",
        "hallazgos": {
            "fiebre": "tipico",
            "rigidez_nuca": "tipico",
            "signos_meningeos": "tipico",
            "cefalea_progresiva": "frecuente",
            "instauracion_horas": "tipico",
            "alteracion_conciencia": "frecuente",
            "fotofobia": "frecuente",
            "vomitos_proyectivos": "frecuente",
            "petequias": "posible",
            "leucocitosis": "frecuente",
            "neutrofilia": "frecuente",
            "pcr_elevada": "frecuente",
            "procalcitonina_elevada": "tipico",
            "lcr_purulento": "tipico",
            "lcr_pleocitosis_pmn": "tipico",
            "lcr_hipoglucorraquia": "tipico",
            "lcr_proteinorraquia": "frecuente",
            "esplenectomia": "posible",
            "foco_orl": "posible",
            "instauracion_semanas": "atipico",
            "lcr_normal": "incompatible",
        },
    },
    {
        "id": "meningitis_virica",
        "nombre": "Meningitis vírica",
        "sistemas": ["infecciosas", "neuro"],
        "edad_tipica": [5, 40],
        "sexo": None,
        "genetica": "Sin base genética relevante.",
        "hallazgos": {
            "fiebre": "frecuente",
            "cefalea_progresiva": "tipico",
            "rigidez_nuca": "frecuente",
            "fotofobia": "frecuente",
            "instauracion_dias": "frecuente",
            "instauracion_horas": "posible",
            "malestar_general": "frecuente",
            "lcr_claro": "tipico",
            "lcr_pleocitosis_linfo": "tipico",
            "lcr_proteinorraquia": "posible",
            "lcr_hipoglucorraquia": "atipico",
            "lcr_pleocitosis_pmn": "atipico",
            "alteracion_conciencia": "atipico",
            "lcr_purulento": "incompatible",
        },
    },
    {
        "id": "encefalitis_herpetica",
        "nombre": "Encefalitis herpética",
        "sistemas": ["infecciosas", "neuro"],
        "edad_tipica": [0, 90],
        "sexo": None,
        "genetica": "Descritos déficits raros de la vía TLR3.",
        "hallazgos": {
            "fiebre": "tipico",
            "alteracion_conducta": "tipico",
            "confusion": "tipico",
            "crisis_convulsiva": "frecuente",
            "afasia": "frecuente",
            "instauracion_dias": "tipico",
            "cefalea_progresiva": "frecuente",
            "alteracion_conciencia": "frecuente",
            "rm_temporal": "tipico",
            "lcr_pleocitosis_linfo": "frecuente",
            "lcr_hematico": "posible",
            "lcr_claro": "frecuente",
            "instauracion_subita": "atipico",
        },
    },
    {
        "id": "hemorragia_subaracnoidea",
        "nombre": "Hemorragia subaracnoidea",
        "sistemas": ["neuro"],
        "edad_tipica": [40, 70],
        "sexo": "predomina_mujer",
        "genetica": "Poliquistosis renal y Ehlers-Danlos; agregación familiar de aneurismas.",
        "hallazgos": {
            "cefalea_brusca": "tipico",
            "instauracion_subita": "tipico",
            "vomitos_proyectivos": "frecuente",
            "rigidez_nuca": "frecuente",
            "alteracion_conciencia": "frecuente",
            "fotofobia": "posible",
            "tc_hemorragia_subaracnoidea": "tipico",
            "lcr_hematico": "tipico",
            "focalidad_motora": "posible",
            "anticoagulacion": "posible",
            "fiebre": "atipico",
            "instauracion_semanas": "atipico",
        },
    },
    {
        "id": "migrana",
        "nombre": "Migraña",
        "sistemas": ["neuro"],
        "edad_tipica": [15, 45],
        "sexo": "predomina_mujer",
        "genetica": "Fuerte agregación familiar; migraña hemipléjica familiar (CACNA1A, ATP1A2, SCN1A).",
        "hallazgos": {
            "cefalea_progresiva": "tipico",
            "curso_recurrente": "tipico",
            "fotofobia": "tipico",
            "aura_visual": "frecuente",
            "vomitos_proyectivos": "posible",
            "instauracion_horas": "frecuente",
            "fiebre": "incompatible",
            "rigidez_nuca": "incompatible",
            "papiledema": "incompatible",
            "alteracion_conciencia": "atipico",
            "crisis_convulsiva": "atipico",
        },
    },
    {
        "id": "tumor_cerebral",
        "nombre": "Tumor cerebral primario",
        "sistemas": ["neuro", "oncohemato"],
        "edad_tipica": [45, 75],
        "sexo": None,
        "genetica": "Li-Fraumeni, neurofibromatosis, Turcot; la mayoría son esporádicos.",
        "hallazgos": {
            "cefalea_matutina": "tipico",
            "cefalea_progresiva": "tipico",
            "instauracion_semanas": "tipico",
            "curso_progresivo": "tipico",
            "papiledema": "frecuente",
            "crisis_convulsiva": "frecuente",
            "focalidad_motora": "frecuente",
            "vomitos_proyectivos": "frecuente",
            "alteracion_conducta": "posible",
            "tc_lesion_ocupante": "tipico",
            "instauracion_subita": "atipico",
            "fiebre": "atipico",
        },
    },
    {
        "id": "lma",
        "nombre": "Leucemia mieloide aguda",
        "sistemas": ["oncohemato"],
        "edad_tipica": [60, 85],
        "sexo": None,
        "genetica": "t(15;17) en la promielocítica, t(8;21), inv(16); riesgo aumentado en síndrome de Down.",
        "hallazgos": {
            "astenia": "tipico",
            "palidez": "tipico",
            "anemia": "tipico",
            "trombopenia": "tipico",
            "blastos_sangre": "tipico",
            "equimosis": "frecuente",
            "sangrado_mucosas": "frecuente",
            "fiebre": "frecuente",
            "pancitopenia": "frecuente",
            "instauracion_semanas": "frecuente",
            "hipertrofia_gingival": "posible",
            "leucocitosis": "posible",
            "ldh_elevada": "frecuente",
            "acido_urico_elevado": "frecuente",
            "quimioterapia_previa": "posible",
            "sindrome_down": "posible",
            "curso_recurrente": "atipico",
        },
    },
    {
        "id": "lla",
        "nombre": "Leucemia linfoblástica aguda",
        "sistemas": ["oncohemato"],
        "edad_tipica": [2, 10],
        "sexo": "predomina_varon",
        "genetica": "Cromosoma Philadelphia t(9;22) de mal pronóstico; síndrome de Down.",
        "hallazgos": {
            "astenia": "tipico",
            "palidez": "tipico",
            "anemia": "tipico",
            "trombopenia": "tipico",
            "blastos_sangre": "tipico",
            "dolor_oseo": "frecuente",
            "adenopatias_generalizadas": "frecuente",
            "hepatomegalia": "frecuente",
            "esplenomegalia": "frecuente",
            "fiebre": "frecuente",
            "equimosis": "frecuente",
            "masa_mediastinica": "posible",
            "sindrome_down": "posible",
            "ldh_elevada": "frecuente",
        },
    },
    {
        "id": "linfoma_hodgkin",
        "nombre": "Linfoma de Hodgkin",
        "sistemas": ["oncohemato"],
        "edad_tipica": [18, 35],
        "sexo": None,
        "genetica": "Asociación con VEB; agregación familiar leve.",
        "hallazgos": {
            "adenopatias_indoloras": "tipico",
            "adenopatias_generalizadas": "frecuente",
            "sudoracion_nocturna": "tipico",
            "perdida_peso": "tipico",
            "febricula": "frecuente",
            "prurito": "frecuente",
            "instauracion_semanas": "tipico",
            "masa_mediastinica": "frecuente",
            "vsg_elevada": "frecuente",
            "ldh_elevada": "posible",
            "esplenomegalia": "posible",
            "astenia": "frecuente",
            "instauracion_subita": "atipico",
            "adenopatias_dolorosas": "atipico",
        },
    },
    {
        "id": "mononucleosis",
        "nombre": "Mononucleosis infecciosa",
        "sistemas": ["infecciosas"],
        "edad_tipica": [15, 25],
        "sexo": None,
        "genetica": "Síndrome linfoproliferativo ligado al X en formas graves.",
        "hallazgos": {
            "odinofagia": "tipico",
            "adenopatias_dolorosas": "tipico",
            "fiebre": "tipico",
            "astenia": "tipico",
            "esplenomegalia": "frecuente",
            "linfocitosis": "tipico",
            "hepatomegalia": "posible",
            "exantema": "posible",
            "malestar_general": "frecuente",
            "instauracion_dias": "frecuente",
            "instauracion_semanas": "posible",
            "blastos_sangre": "incompatible",
        },
    },
    {
        "id": "tuberculosis_pulmonar",
        "nombre": "Tuberculosis pulmonar",
        "sistemas": ["infecciosas"],
        "edad_tipica": [20, 60],
        "sexo": None,
        "genetica": "Polimorfismos de susceptibilidad descritos; sin herencia mendeliana.",
        "hallazgos": {
            "tos": "tipico",
            "instauracion_semanas": "tipico",
            "sudoracion_nocturna": "tipico",
            "perdida_peso": "tipico",
            "febricula": "frecuente",
            "hemoptisis": "frecuente",
            "expectoracion": "frecuente",
            "rx_cavitacion_apical": "tipico",
            "astenia": "frecuente",
            "vih": "posible",
            "contacto_epidemico": "frecuente",
            "advp": "posible",
            "vsg_elevada": "frecuente",
            "instauracion_subita": "atipico",
        },
    },
    {
        "id": "neumonia_adquirida",
        "nombre": "Neumonía adquirida en la comunidad",
        "sistemas": ["infecciosas"],
        "edad_tipica": [0, 90],
        "sexo": None,
        "genetica": "Sin base genética relevante.",
        "hallazgos": {
            "fiebre": "tipico",
            "tos": "tipico",
            "expectoracion": "frecuente",
            "disnea": "frecuente",
            "dolor_pleuritico": "frecuente",
            "instauracion_dias": "tipico",
            "rx_condensacion": "tipico",
            "leucocitosis": "frecuente",
            "neutrofilia": "frecuente",
            "pcr_elevada": "frecuente",
            "procalcitonina_elevada": "frecuente",
            "confusion": "posible",
            "tabaquismo": "posible",
            "instauracion_semanas": "atipico",
        },
    },
]

PATOLOGIAS_POR_ID = {p["id"]: p for p in PATOLOGIAS}
