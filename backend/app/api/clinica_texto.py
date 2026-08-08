"""
EMPAREJAR LO QUE SE ESCRIBE A MANO CON EL CATALOGO.

EL PROBLEMA QUE RESUELVE

La primera version le mandaba a la IA el catalogo entero -228 hallazgos,
casi 10.000 caracteres- en cada peticion, y le pedia que devolviera los
identificadores exactos. No funciono: los cinco proveedores agotaban su
tiempo de espera uno detras de otro y la pantalla daba un 502 al cabo de
casi cuatro minutos. Un envio asi en cada tecleo era insostenible.

EL REPARTO CORRECTO

La IA hace lo unico que solo ella puede hacer: entender que "le empezo de
golpe un dolor de cabeza brutal" quiere decir "cefalea de inicio brusco".
Eso cabe en un envio de dos lineas.

El emparejamiento con el catalogo es comparar textos, y comparar textos lo
hace mejor el codigo: es instantaneo, no cuesta nada, da siempre el mismo
resultado y no depende de que un modelo copie bien un identificador de una
lista de doscientos.

POR QUE ES ESTRICTO A PROPOSITO

Colar un hallazgo equivocado es peor que no colar ninguno. Uno que falta se
ve -no aparece en la lista y lo añades a mano-; uno equivocado entra en el
diferencial, cambia los porcentajes y nadie se entera. Ante la duda, este
modulo prefiere no emparejar y decir que no encontro sitio.
"""
from __future__ import annotations

import re
import unicodedata

from app.api import clinica_base

_VACIAS = {"de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas",
           "en", "con", "por", "y", "o", "a", "al", "que", "se", "su", "sus",
           "mas", "muy", "para", "como", "hace", "tiene", "presenta", "refiere"}

# Formas de decir lo mismo que un emparejamiento por palabras no pilla, y que
# salen constantemente al contar un caso con naturalidad.
_SINONIMOS: dict[str, list[str]] = {
    "cefalea_progresiva": ["dolor de cabeza", "cefalalgia", "cefalea"],
    "cefalea_brusca": ["cefalea en trueno", "dolor de cabeza de golpe",
                       "el peor dolor de cabeza de su vida", "cefalea subita"],
    "rigidez_nuca": ["cuello rigido", "nuca rigida", "rigidez cervical"],
    "disnea": ["falta de aire", "ahogo", "dificultad respiratoria", "disneico"],
    "astenia": ["cansancio", "fatiga", "decaimiento"],
    "anorexia": ["falta de apetito", "inapetencia"],
    "perdida_peso": ["adelgazamiento", "ha adelgazado", "ha perdido kilos"],
    "nauseas_vomitos": ["vomitos", "nauseas", "vomita"],
    "alteracion_conciencia": ["obnubilado", "estuporoso", "somnoliento",
                              "bajo nivel de conciencia", "inconsciente"],
    "confusion": ["desorientado", "desorientacion", "confuso"],
    "focalidad_motora": ["hemiparesia", "paresia", "perdida de fuerza",
                         "no mueve el brazo", "hemiplejia"],
    "crisis_convulsiva": ["convulsion", "convulsiones", "crisis comicial",
                          "ha convulsionado", "epilepsia"],
    "disuria": ["escozor al orinar", "sindrome miccional", "molestias al orinar"],
    "ictericia": ["piel amarilla", "tinte icterico", "ictericio"],
    "hemoptisis": ["esputo con sangre", "tose sangre", "escupe sangre"],
    "esplenomegalia": ["bazo grande", "bazo palpable", "bazo aumentado"],
    "hepatomegalia": ["higado grande", "higado palpable", "higado aumentado"],
    "petequias": ["purpura", "puntitos rojos", "petequial"],
    "trombopenia": ["plaquetas bajas", "trombocitopenia"],
    "anemia": ["hemoglobina baja", "anemico"],
    "leucocitosis": ["leucocitos altos", "leucocitosis marcada"],
    "leucopenia": ["leucocitos bajos"],
    "neutropenia": ["neutrofilos bajos"],
    "insuficiencia_renal": ["creatinina alta", "fallo renal", "deterioro de funcion renal"],
    "fiebre": ["febril", "fiebre alta", "pico febril"],
    "febricula": ["decimas", "febricular"],
    "adenopatias_indoloras": ["ganglios indoloros", "bultos indoloros"],
    "adenopatias_dolorosas": ["ganglios dolorosos"],
    "adenopatias_generalizadas": ["ganglios por todo el cuerpo", "poliadenopatias"],
    "blastos_sangre": ["blastos", "celulas blasticas"],
    "sudoracion_nocturna": ["suda por la noche", "sudores nocturnos"],
    "dolor_oseo": ["dolor en los huesos", "dolores oseos"],
    "instauracion_subita": ["de golpe", "de repente", "subito", "brusco"],
    "curso_progresivo": ["va a peor", "empeora progresivamente"],
    "curso_recurrente": ["episodios previos", "le ha pasado otras veces", "recurrente"],
    "transaminasas_elevadas": ["transaminasas altas", "got y gpt altas", "hipertransaminasemia"],
    "vsg_elevada": ["velocidad de sedimentacion alta"],
    "pcr_elevada": ["proteina c reactiva alta", "pcr alta"],
    "hipoacusia": ["oye mal", "sordera"],
    "diabetes": ["diabetico", "diabetes mellitus"],
    "artralgias": ["gonalgia", "dolor articular", "dolor de rodilla", "coxalgia"],
    "hemartros": ["sangre en la articulacion", "hemartrosis"],
    "tumefaccion_articular": ["tumefaccion", "rodilla hinchada", "articulacion hinchada",
                              "hinchazon articular"],
    "eritema_local": ["eritema", "rojez", "enrojecimiento", "zona roja"],
    "ttpa_prolongado": ["tiempo de tromboplastina parcial activado prolongado",
                        "ttpa alargado", "aptt prolongado"],
    "dimero_d_elevado": ["dimero d alto"],
    "antecedente_familiar_sangrado": ["familiares que sangran",
                                      "antecedentes familiares de hemorragia"],
    "hipotension": ["tension baja", "presion arterial baja", "hipotenso"],
    "hipertension": ["tension alta", "presion arterial alta", "hipertenso"],
    "tabaquismo": ["fumador", "fuma"],
    "alcoholismo_cronico": ["bebedor", "alcoholico", "enolismo"],
}


def _raiz(palabra: str) -> str:
    """
    Quita el plural, a lo bruto.

    "antecedente familiar de sangrado" no encajaba con "Antecedentes
    familiares de sangrado" por dos eses. Un lematizador de verdad seria
    pasarse; con recortar el plural, y aplicandolo a los dos lados, basta:
    aunque el recorte sea imperfecto, lo es igual en ambos y siguen
    coincidiendo.
    """
    if len(palabra) > 5 and palabra.endswith("es"):
        return palabra[:-2]
    if len(palabra) > 4 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def _normalizar(texto: str) -> list[str]:
    """Palabras significativas, sin tildes, sin parentesis y sin relleno."""
    t = re.sub(r"\([^)]*\)", " ", (texto or "").lower())
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return [_raiz(p) for p in t.split() if p not in _VACIAS and len(p) > 2]


def _construir_indice() -> list[tuple[str, list[set[str]]]]:
    """
    Cada hallazgo con VARIAS bolsas de palabras: la de su nombre y una por
    cada sinonimo.

    Separadas y no en un mismo saco a proposito. Juntandolo todo, un
    hallazgo con muchos sinonimos acumula tantas palabras que ya no encaja
    con ninguna frase concreta: cuantos mas nombres tuviera, peor
    funcionaria. Que compita cada forma por su cuenta y gane la mejor.
    """
    indice = []
    for h in clinica_base.HALLAZGOS:
        # Los nombres con barra son dos formas de decir lo mismo, y hay que
        # tratarlas como tales. Metidas en un mismo saco fallaba lo obvio:
        # "equimosis" contra "Equimosis / hematomas espontáneos" solo cubria
        # una de tres palabras y se quedaba por debajo del corte, asi que un
        # hallazgo que SI estaba en el catalogo salia como desconocido.
        bolsas = [set(_normalizar(parte)) for parte in re.split(r"[/,]", h["nombre"])]
        for extra in _SINONIMOS.get(h["id"], []):
            b = set(_normalizar(extra))
            if b:
                bolsas.append(b)
        indice.append((h["id"], [b for b in bolsas if b]))
    return indice


_INDICE: list[tuple[str, list[set[str]]]] | None = None

# Cuanto tienen que parecerse para darlo por bueno. Subirlo deja fuera
# emparejamientos correctos; bajarlo empieza a colar los equivocados, que es
# el error caro.
_MINIMO = 0.6


def emparejar(frase: str) -> str | None:
    """El hallazgo del catalogo que mejor encaja con esa frase, o nada."""
    global _INDICE
    if _INDICE is None:
        _INDICE = _construir_indice()

    dichas = set(_normalizar(frase))
    if not dichas:
        return None

    mejor, mejor_nota = None, 0.0
    for hid, bolsas in _INDICE:
        for palabras in bolsas:
            comunes = dichas & palabras
            if not comunes:
                continue
            cubierto = len(comunes) / len(palabras)   # cuanto del hallazgo aparece
            precision = len(comunes) / len(dichas)    # cuanto de la frase se aprovecha
            nota = (2 * cubierto * precision) / (cubierto + precision)
            if nota > mejor_nota:
                mejor, mejor_nota = hid, nota
    return mejor if mejor_nota >= _MINIMO else None
