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

from fastapi import APIRouter, Body, HTTPException

from app.api import clinica_base, clinica_motor, clinica_store
from app.api.clases import _pedir_a_la_ia
from app.core.config import get_settings
from app.providers.registry import ProviderRegistry

router = APIRouter(prefix="/clinica", tags=["clinica"])

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
    orden = {"tipico": 0, "frecuente": 1, "posible": 2, "atipico": 3, "incompatible": 4}
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
