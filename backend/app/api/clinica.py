"""
LABERINTO CLINICO: navegar un diagnostico diferencial paso a paso.

QUE ES

Una herramienta de ESTUDIO. Metes datos clinicos poco a poco y ves, en cada
paso, que sistemas y que patologias siguen en juego, cuales se han caido y
-sobre todo- POR QUE se han caido.

Lo que enseña no es el resultado: es el camino. Si la app se limitara a
decir "esto es una meningitis" no serviria para aprender nada.

QUE NO ES

No sirve para diagnosticar a nadie. Va escrito en la pantalla, no escondido
en un aviso legal al pie.

COMO SE REPARTE EL TRABAJO

El razonamiento -puntuar, descartar, ordenar, decidir que conviene preguntar
ahora- es codigo puro, en clinica_motor.py. La IA no entra ahi: le pides un
porcentaje y se lo inventa, y un numero inventado con dos decimales parece
mas fiable que un "probable" honesto.

La IA solo se usa para EXPLICAR una patologia concreta cuando la abres, y lo
que escribe se guarda: la segunda vez ya no se pide. Cuarenta patologias son
cuarenta llamadas en toda la vida de la app.

Efecto practico: se puede navegar casos durante horas sin gastar nada.
"""
from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, Body, HTTPException

from app.api import clinica_base, clinica_motor, clinica_store, clinica_texto
from app.core.config import get_settings
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry

router = APIRouter(prefix="/clinica", tags=["clinica"])

# Misma cadena de respaldo que el resto del proyecto, pero con su propia
# copia: colgarse del ayudante privado de otra app era pedir que el dia que
# alguien lo tocara alli se rompiera aqui sin avisar.
_PROVEEDORES = [
    ("gemini2", "gemini-3.6-flash"),
    ("gemini", "gemini-3.6-flash"),
    ("glm", "glm-4.7-flash"),
    ("groq", "llama-3.3-70b-versatile"),
    ("cerebras", "gpt-oss-120b"),
]

# VEINTE SEGUNDOS, NO CUARENTA Y CINCO.
#
# Con cinco proveedores y 45 segundos cada uno, un fallo tardaba casi cuatro
# minutos en aparecer en pantalla. Cuatro minutos de boton mudo no se
# distinguen de un cuelgue, y encima invitan a darle otra vez, que empeora
# las cosas. Aqui todo es interactivo: mas vale enterarse pronto de que no
# se puede.
_ESPERA = 20.0


async def _pedir_a_la_ia(registro, mensajes, temperatura: float = 0.3) -> str:
    """Prueba los proveedores por orden y cuenta que ha fallado en cada uno.

    Tener clave no es tener cuota: por eso se prueba de verdad en vez de
    preguntar si esta configurado, y por eso se guardan TODOS los fallos y
    no solo el ultimo -ver cuatro motivos distintos dice mucho mas que ver
    el ultimo-.
    """
    intentos: list[str] = []
    for nombre_prov, nombre_mod in _PROVEEDORES:
        try:
            proveedor = registro.get(nombre_prov)
        except KeyError:
            intentos.append(f"{nombre_prov}: no existe en el servidor")
            continue
        if not proveedor.is_configured():
            intentos.append(f"{nombre_prov}: sin clave configurada")
            continue
        try:
            return await asyncio.wait_for(
                proveedor.chat(mensajes, model=nombre_mod, temperature=temperatura),
                timeout=_ESPERA,
            )
        except asyncio.TimeoutError:
            intentos.append(f"{nombre_prov}: no contestó en {int(_ESPERA)}s")
        except ProviderError as e:
            intentos.append(f"{nombre_prov}: {e}")
        except Exception as e:
            intentos.append(f"{nombre_prov}: {type(e).__name__} {e}")

    detalle = "\n".join(f"· {i}" for i in intentos) or "· no hay ningún proveedor configurado"
    raise HTTPException(502, "Ningún proveedor de IA ha podido con esto:\n" + detalle)


_COSTES = {h["id"]: h.get("coste", 1) for h in clinica_base.HALLAZGOS}

AVISO = ("Herramienta de estudio. No sirve para diagnosticar a ninguna persona. "
         "Los porcentajes miden parecido con el patrón típico de cada ficha, "
         "no probabilidad clínica.")

_INSTRUCCION_FICHA = (
    "Eres un profesor de medicina explicando una patología a un estudiante "
    "que la está viendo dentro de un diferencial. Te doy la ficha de datos y "
    "tú escribes SOLO la parte explicativa. Reglas:\n"
    "1. Ve al grano. Frases cortas. Nada de introducciones ni de resumir lo "
    "que te he dado.\n"
    "2. Explica el MECANISMO, no la lista. El estudiante ya tiene la lista de "
    "síntomas delante: lo que no tiene es por qué se producen.\n"
    "3. Devuelve exactamente estos seis apartados, con este título y en este "
    "orden, cada uno de 2 a 4 frases:\n"
    "POR QUE DA ESTA CLINICA\n"
    "QUE SE PIDE Y POR QUE\n"
    "QUE ESPERAMOS VER\n"
    "TRATAMIENTO\n"
    "QUE ESPERAMOS DEL TRATAMIENTO\n"
    "EFECTOS SECUNDARIOS\n"
    "4. No uses markdown, ni asteriscos, ni viñetas. Texto plano.\n"
    "5. No inventes cifras concretas de dosis. Si algo depende del caso, dilo "
    "en vez de dar un número falso.\n"
    "6. Escribe en español de España."
)


_INSTRUCCION_INTERPRETAR = (
    "Extraes los hallazgos clínicos de un caso escrito en lenguaje "
    "corriente. Reglas:\n"
    "1. Devuelve SOLO un JSON: una lista de objetos "
    "{\"hallazgo\": \"...\", \"estado\": \"presente\" o \"ausente\"}.\n"
    "2. Usa el término médico estándar, en singular y sin adornos: "
    "'dolor de cabeza que empezó de golpe' es 'cefalea de inicio brusco'; "
    "'tenía 38.5' es 'fiebre'; 'el cuello rígido' es 'rigidez de nuca'.\n"
    "3. 'ausente' es para lo que el texto NIEGA expresamente ('sin fiebre', "
    "'no refiere cefalea', 'afebril'). Eso es información valiosa: no la "
    "tires.\n"
    "4. NO deduzcas ni completes. Si el texto dice fiebre, pon fiebre; no "
    "añadas escalofríos porque suelan ir juntos. Solo lo que está escrito.\n"
    "5. La edad y el sexo NO son hallazgos: no los incluyas.\n"
    "6. Un hallazgo por entrada. Si una frase mete tres cosas, sepáralas.\n"
    "7. Sin markdown, sin explicaciones, sin comentarios. Solo el JSON."
)


def _extraer_lista(texto: str) -> list:
    """
    Saca la lista JSON de lo que conteste el modelo.

    Aunque se le pida el JSON pelado, a veces lo envuelve en explicaciones o
    en un bloque de codigo. Recortar por el primer corchete y el ultimo es
    mas fiable que confiar en que obedezca.
    """
    if not texto:
        return []
    limpio = re.sub(r"^```[a-z]*|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    a, b = limpio.find("["), limpio.rfind("]")
    if a == -1 or b == -1 or b < a:
        return []
    try:
        d = json.loads(limpio[a:b + 1])
    except json.JSONDecodeError:
        return []
    return d if isinstance(d, list) else []


@router.post("/interpretar")
async def interpretar(cuerpo: dict = Body(...)):
    """
    ESCRIBIR EL CASO A MANO.

    Elegir de la lista es fiable pero lento, y no se parece a como llega un
    caso de verdad: llega contado. Aqui se escribe en lenguaje normal y la
    IA lo traduce a hallazgos del catalogo.

    DOS CAUTELAS, Y NO SON MENORES

    La primera: lo que sale NO entra solo en el caso. Se propone, y hay que
    aceptarlo uno a uno. Si la IA entiende mal una frase y ese hallazgo
    entrara directo, el diferencial saldria torcido sin que nadie se
    enterase -que es exactamente el fallo silencioso que esta app intenta
    no cometer-.

    La segunda: se le prohibe deducir. Si el texto dice fiebre, pone fiebre;
    no añade escalofrios porque suelan ir juntos. Completar por su cuenta
    seria meter en el caso datos que el paciente no ha dado.

    Y traduce tambien las negaciones ("sin fiebre", "afebril"), porque en un
    diferencial lo que se descarta pesa tanto como lo que se encuentra.
    """
    texto = (cuerpo.get("texto") or "").strip()
    if not texto:
        raise HTTPException(400, "Escribe algo del caso antes de interpretarlo.")
    if len(texto) > 4000:
        texto = texto[:4000]

    registro = ProviderRegistry(get_settings())
    bruto = await _pedir_a_la_ia(registro, [
        {"role": "system", "content": _INSTRUCCION_INTERPRETAR},
        {"role": "user", "content": "CASO:\n" + texto},
    ], temperatura=0.1)

    vistos: set[str] = set()
    salida = []
    sin_sitio: list[str] = []
    for item in _extraer_lista(bruto):
        if not isinstance(item, dict):
            continue
        frase = (item.get("hallazgo") or "").strip()
        if not frase:
            continue
        estado = item.get("estado")
        if estado not in ("presente", "ausente"):
            estado = "presente"

        hid = clinica_texto.emparejar(frase)
        # Lo que no encuentra sitio NO se tira en silencio: se devuelve para
        # poder enseñarlo. Que la app se coma un dato sin decir nada seria el
        # mismo fallo callado que perseguimos en todo lo demas.
        if hid is None:
            sin_sitio.append(frase)
            continue
        if hid in vistos:
            continue
        vistos.add(hid)
        h = clinica_base.HALLAZGOS_POR_ID[hid]
        salida.append({"id": hid, "nombre": h["nombre"], "bloque": h["bloque"],
                       "pestana": h["pestana"], "estado": estado, "dijiste": frase})

    return {"propuestos": salida, "sin_sitio": sin_sitio, "aviso": AVISO}


@router.post("/imagen")
async def imagen(cuerpo: dict = Body(...)):
    """
    DESCRIBIR UNA IMAGEN Y QUE TE CORRIJAN.

    Aqui no se sube ninguna imagen: se escribe lo que uno cree que ve, con
    su vocabulario, y se corrige la descripcion. Suena raro y es a proposito.

    Delante del monitor lo que falla casi nunca es "ver la mancha": es
    nombrarla. Decir hipointenso sin decir en que secuencia, llamar denso a
    algo en una ecografia, describir un nodulo sin decir donde esta ni como
    tiene los bordes. Eso se entrena escribiendo y que te lo corrijan, y no
    hace falta la imagen delante para entrenarlo.

    La respuesta separa a proposito lo que esta bien dicho, lo que esta mal
    dicho y lo que falta por decir, antes de entrar en que puede ser. El
    orden es el mensaje: primero se describe bien, y solo despues se
    interpreta.
    """
    descripcion = (cuerpo.get("descripcion") or "").strip()
    if not descripcion:
        raise HTTPException(400, "Describe lo que ves antes de pedir la corrección.")
    if len(descripcion) > 3000:
        descripcion = descripcion[:3000]
    prueba = (cuerpo.get("prueba") or "").strip()[:120]
    contexto = (cuerpo.get("contexto") or "").strip()[:600]

    partes = [f"PRUEBA: {prueba or 'no la ha dicho (pídesela)'}"]
    if contexto:
        partes.append(f"CASO ABIERTO (solo como contexto): {contexto}")
    partes.append("DESCRIPCIÓN DEL ESTUDIANTE:\n" + descripcion)

    registro = ProviderRegistry(get_settings())
    texto = await _pedir_a_la_ia(registro, [
        {"role": "system", "content": _INSTRUCCION_IMAGEN},
        {"role": "user", "content": "\n\n".join(partes)},
    ], temperatura=0.2)

    return {"correccion": (texto or "").strip(), "aviso": AVISO}


@router.get("/catalogo")
async def catalogo():
    """
    Todo lo que la pantalla necesita para arrancar, de una vez.

    Va junto a proposito: son datos que no cambian durante la sesion, y
    pedirlos en tres viajes distintos solo añadiria esperas al abrir la app
    en el movil.
    """
    return {
        "aviso": AVISO,
        "sistemas": clinica_base.SISTEMAS,
        "pestanas": clinica_base.pestanas(),
        "bloques": clinica_base.bloques(),
        "patologias": [
            {"id": p["id"], "nombre": p["nombre"], "sistemas": p.get("sistemas", [])}
            for p in clinica_base.PATOLOGIAS
        ],
    }


@router.post("/evaluar")
async def evaluar(cuerpo: dict = Body(...)):
    """
    El paso central: dado lo que se sabe del caso, que queda en pie.

    Sin IA y sin guardar nada. Es una funcion pura: los mismos datos dan
    siempre el mismo resultado, que es justo lo que hace falta para poder
    estudiar con esto.
    """
    datos = cuerpo.get("datos") or []
    if not isinstance(datos, list):
        raise HTTPException(400, "El campo 'datos' tiene que ser una lista.")

    previas = cuerpo.get("previas") or {}
    resultado = clinica_motor.evaluar(datos, clinica_base.PATOLOGIAS, previas)
    resultado["sugerencias"] = [
        {"id": h, "nombre": clinica_base.HALLAZGOS_POR_ID.get(h, {}).get("nombre", h)}
        for h in clinica_motor.sugerir(datos, clinica_base.PATOLOGIAS, costes=_COSTES)
    ]
    resultado["aviso"] = AVISO
    return resultado


@router.get("/ficha/{patologia}")
async def ficha(patologia: str):
    """
    La ficha completa de una patologia: los datos fijos mas la explicacion.

    La explicacion se pide a la IA la PRIMERA vez y se guarda. A partir de
    ahi sale de la base de datos. Ademas de no gastar, esto tiene una
    ventaja que importa mas: el texto no cambia cada vez que abres la misma
    patologia. Estudiar con algo que se reescribe solo no funciona.
    """
    pat = clinica_base.PATOLOGIAS_POR_ID.get(patologia)
    if not pat:
        raise HTTPException(404, "Esa patología no está en la base.")

    hallazgos = [
        {"id": hid, "nombre": clinica_base.HALLAZGOS_POR_ID.get(hid, {}).get("nombre", hid),
         "relacion": rel}
        for hid, rel in pat.get("hallazgos", {}).items()
    ]
    orden = {"patognomonico": 0, "tipico": 1, "frecuente": 2, "posible": 3,
             "atipico": 4, "incompatible": 5}
    hallazgos.sort(key=lambda h: (orden.get(h["relacion"], 9), h["nombre"]))

    salida = {
        "id": pat["id"],
        "nombre": pat["nombre"],
        "sistemas": [clinica_base.SISTEMAS.get(s, s) for s in pat.get("sistemas", [])],
        "edad_tipica": pat.get("edad_tipica"),
        "sexo": pat.get("sexo"),
        "genetica": pat.get("genetica", ""),
        "hallazgos": hallazgos,
        "aviso": AVISO,
    }

    guardada = await clinica_store.leer("ficha", pat["id"])
    if guardada and guardada.get("explicacion"):
        salida["explicacion"] = guardada["explicacion"]
        salida["recien_generada"] = False
        return salida

    resumen = "\n".join([
        f"Patología: {pat['nombre']}",
        f"Sistemas: {', '.join(salida['sistemas'])}",
        f"Edad típica: {pat.get('edad_tipica')}",
        f"Genética: {pat.get('genetica', '')}",
        "Hallazgos típicos: " + ", ".join(h["nombre"] for h in hallazgos if h["relacion"] == "tipico"),
        "Frecuentes: " + ", ".join(h["nombre"] for h in hallazgos if h["relacion"] == "frecuente"),
        "La descartan: " + ", ".join(h["nombre"] for h in hallazgos if h["relacion"] == "incompatible"),
    ])

    registro = ProviderRegistry(get_settings())
    texto = await _pedir_a_la_ia(registro, [
        {"role": "system", "content": _INSTRUCCION_FICHA},
        {"role": "user", "content": resumen},
    ], temperatura=0.2)

    salida["explicacion"] = (texto or "").strip()
    salida["recien_generada"] = True
    if salida["explicacion"]:
        await clinica_store.guardar("ficha", pat["id"], {"explicacion": salida["explicacion"]})
    return salida


_INSTRUCCION_MECANISMOS = (
    "Eres un profesor de medicina. Te doy una patología y la lista de sus "
    "hallazgos. Para CADA uno explicas POR QUÉ lo produce esa enfermedad. "
    "Reglas:\n"
    "1. Devuelve SOLO un JSON: una lista de objetos "
    "{\"id\": \"...\", \"causa\": \"...\"}. El id es el que te doy, copiado "
    "tal cual.\n"
    "2. La causa es el MECANISMO, en una o dos frases. Qué pasa dentro del "
    "cuerpo para que aparezca ese signo. No repitas el nombre del hallazgo "
    "ni digas que es frecuente: eso ya se sabe.\n"
    "3. Si un hallazgo está marcado como ATÍPICO o INCOMPATIBLE, explica por "
    "qué NO cabe esperarlo en esta enfermedad y qué sugeriría si apareciera.\n"
    "4. Si un hallazgo es PATOGNOMÓNICO, explica qué lo hace exclusivo de "
    "esta enfermedad y no de las que se le parecen.\n"
    "5. Nada de introducciones ni despedidas. Sin markdown. Español de "
    "España.\n"
    "6. Una entrada por cada id que te doy, ni una más ni una menos."
)


@router.get("/mecanismos/{patologia}")
async def mecanismos(patologia: str):
    """
    POR QUE CADA HALLAZGO ENCAJA CON ESTE DIAGNOSTICO.

    Llegar al diagnostico y quedarse ahi enseña la mitad. Lo que se recuerda
    -y lo que sirve en el siguiente caso, que sera distinto- es el mecanismo:
    por que ESTA enfermedad produce ESTE signo.

    Se generan TODOS los hallazgos de la patologia de una vez, no solo los
    del caso abierto, y se guardan. Asi cada patologia cuesta una unica
    llamada en toda la vida de la app, y el siguiente caso que caiga en el
    mismo diagnostico ya los tiene escritos. Ademas, al no depender del caso,
    el texto no cambia de una vez a otra: estudiar con algo que se reescribe
    solo no funciona.
    """
    pat = clinica_base.PATOLOGIAS_POR_ID.get(patologia)
    if not pat:
        raise HTTPException(404, "Esa patología no está en la base.")

    guardado = await clinica_store.leer("mecanismos", pat["id"])
    if guardado and guardado.get("causas"):
        return {"id": pat["id"], "nombre": pat["nombre"],
                "causas": guardado["causas"], "recien_generado": False}

    lista = [f"{hid} | {clinica_base.HALLAZGOS_POR_ID.get(hid, {}).get('nombre', hid)} | {rel}"
             for hid, rel in pat.get("hallazgos", {}).items()]
    peticion = (f"PATOLOGÍA: {pat['nombre']}\n"
                f"GENÉTICA: {pat.get('genetica', '')}\n\n"
                "HALLAZGOS (id | nombre | relación):\n" + "\n".join(lista))

    registro = ProviderRegistry(get_settings())
    bruto = await _pedir_a_la_ia(registro, [
        {"role": "system", "content": _INSTRUCCION_MECANISMOS},
        {"role": "user", "content": peticion},
    ], temperatura=0.2)

    causas: dict[str, str] = {}
    for item in _extraer_lista(bruto):
        if not isinstance(item, dict):
            continue
        hid, causa = item.get("id"), (item.get("causa") or "").strip()
        # Solo se acepta lo que corresponde a un hallazgo REAL de esta
        # patologia: si el modelo se inventa uno, aqui se queda.
        if hid in pat.get("hallazgos", {}) and causa:
            causas[hid] = causa

    if causas:
        await clinica_store.guardar("mecanismos", pat["id"], {"causas": causas})
    return {"id": pat["id"], "nombre": pat["nombre"], "causas": causas,
            "recien_generado": True}


@router.post("/caso")
async def guardar_caso(cuerpo: dict = Body(...)):
    nombre = (cuerpo.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "Hace falta un nombre para guardar el caso.")
    datos = cuerpo.get("datos") or []
    propietario = cuerpo.get("propietario") or ""
    await clinica_store.guardar("caso", nombre, {"nombre": nombre, "datos": datos}, propietario)
    return {"ok": True, "nombre": nombre}


@router.get("/casos")
async def listar_casos(propietario: str = ""):
    return {"casos": await clinica_store.listar_casos(propietario)}


@router.get("/caso/{nombre}")
async def leer_caso(nombre: str, propietario: str = ""):
    caso = await clinica_store.leer("caso", nombre, propietario)
    if caso is None:
        raise HTTPException(404, "Ese caso no está guardado.")
    return caso


@router.delete("/caso/{nombre}")
async def borrar_caso(nombre: str, propietario: str = ""):
    if not await clinica_store.borrar_caso(nombre, propietario):
        raise HTTPException(404, "Ese caso no está guardado.")
    return {"ok": True}
