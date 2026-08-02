"""
REDACCION DE DOCUMENTOS POLICIALES A PARTIR DE UN DICTADO.

QUE HACE

El agente dicta lo que ha pasado, con sus palabras y en desorden, como
se lo contaria a un compañero. La herramienta lo transcribe y lo redacta
en el formato que toca: parte de intervencion, comparecencia de
funcionarios o denuncia de victima. El resultado se descarga como
fichero de texto para llevarlo en un pendrive y pegarlo en SIDENPOL.

LO QUE **NO** HACE, A PROPOSITO

1. No rellena los campos cerrados de SIDENPOL (filiaciones, DNI,
   domicilios, matriculas, hora). Esos se meten en SIDENPOL, que ya los
   tiene estructurados, y deducirlos de un audio es justo el terreno
   donde un modelo rellena huecos con datos verosimiles e inventados.

2. No escribe las formulas legales. Van literales desde
   policia_plantillas.py, por el motivo que se explica alli.

3. No convierte en hecho lo que es una manifestacion. Esta es LA regla
   dura de todo el modulo, y esta explicada en _INSTRUCCION_COMUN.

4. No decide la calificacion penal. Sugiere, cita el articulo y dice en
   que se apoya, para que la decision siga siendo de quien firma.

AVISO SOBRE DATOS

Construido para trabajar con CASOS FICTICIOS. Con datos reales de
personas -victimas, denunciados, delitos- entra en juego la normativa
de tratamiento de datos con fines policiales (LO 7/2021, Directiva UE
2016/680), y esta app envia el audio y el texto a proveedores de IA de
terceros paises. Eso habria que resolverlo antes, y no es un detalle de
implementacion: es la primera pregunta.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api import clases_audio, policia_plantillas
from app.core.config import get_settings
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry

router = APIRouter(prefix="/policia", tags=["policia"])

_GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODELO_AUDIO = "whisper-large-v3-turbo"

# Mismo orden de preferencia que en clases: se prueban de verdad, uno
# detras de otro, porque tener clave no es tener cuota.
_PROVEEDORES = [
    ("cerebras", "gpt-oss-120b"),
    ("glm", "glm-4.7-flash"),
    ("groq", "llama-3.3-70b-versatile"),
]


# =====================================================================
# LA REGLA QUE NO SE NEGOCIA
# =====================================================================
_INSTRUCCION_COMUN = (
    "Eres un asistente que ayuda a redactar documentos de la Policía "
    "Nacional española a partir del dictado de un agente. Trabajas SOLO "
    "con el material que se te da.\n\n"

    "=== REGLA PRINCIPAL: NO CONVIERTAS EN HECHO LO QUE ES UNA MANIFESTACIÓN ===\n"
    "Esta es la regla más importante de todas y está por encima de "
    "cualquier otra consideración de estilo.\n\n"
    "En un documento policial hay una diferencia jurídica enorme entre "
    "lo que los agentes han comprobado y lo que alguien les ha contado. "
    "Si el dictado dice que una persona relata algo, el texto NO puede "
    "afirmarlo como ocurrido: tiene que atribuirlo a quien lo dice.\n\n"
    "  MAL:  «Los individuos lo retuvieron durante tres horas.»\n"
    "  BIEN: «El informante manifiesta que, al parecer, lo habrían "
    "retenido durante unas tres horas.»\n\n"
    "Usa y CONSERVA las fórmulas cautelares propias del lenguaje "
    "policial: «manifiesta que», «según el informante», «al parecer», "
    "«presuntamente», «refiere que». Si el dictado ya las trae, "
    "mantenlas todas. Si el agente relata algo que él mismo ha "
    "presenciado o comprobado, entonces sí se redacta como hecho.\n\n"

    "=== NO INVENTES NADA ===\n"
    "No añadas datos que no estén en el dictado: ni nombres, ni horas, "
    "ni direcciones, ni matrículas, ni cantidades. Si falta un dato que "
    "el documento normalmente llevaría, escribe [PENDIENTE] en su lugar. "
    "Un hueco visible se rellena; un dato inventado que suena bien pasa "
    "desapercibido y acaba firmado.\n\n"

    "=== ESTILO ===\n"
    "- Tercera persona e impersonal. Nunca primera persona.\n"
    "- Los agentes se citan por indicativo o cargo («la dotación Z-81», "
    "«los funcionarios actuantes»), nunca por su nombre.\n"
    "- Registro formal y sobrio. Sin adjetivos valorativos ni "
    "literatura: no describas a nadie como nervioso, agresivo o "
    "sospechoso salvo que el dictado lo diga y como observación.\n"
    "- Párrafos corridos. Nada de listas con guiones ni de negritas.\n"
    "- Orden cronológico.\n"
)

_INSTRUCCION_PARTE = _INSTRUCCION_COMUN + (
    "\n=== DOCUMENTO: DESCRIPCIÓN DE LA ACTUACIÓN (PARTE DE INTERVENCIÓN) ===\n"
    "Redacta el cuerpo del apartado «DESCRIPCIÓN DE LA ACTUACIÓN».\n\n"
    "En PRESENTE de indicativo, que es como se redactan estos partes: "
    "«la sala operativa C-80 recibe llamada…», «la dotación Z-81 realiza "
    "una batida por…», «se realizan gestiones para…».\n\n"
    "Estructura habitual, si el dictado da para ello:\n"
    "1. Origen: cómo llega el servicio a la dotación (llamada a la sala "
    "C-80, requerimiento en la vía pública, de oficio…).\n"
    "2. Qué se hace al llegar y qué se observa o comprueba.\n"
    "3. Lo que manifiestan las personas presentes, atribuido a ellas.\n"
    "4. Gestiones realizadas y su resultado.\n"
    "5. Cierre: destino de lo actuado (a quién se da cuenta, qué queda "
    "pendiente).\n\n"
    "No pongas encabezados ni numeres los párrafos: es texto seguido "
    "para pegar en el campo de SIDENPOL.\n"
    "No incluyas filiaciones completas (nombre, DNI, domicilio): esos "
    "datos van en los campos cerrados del sistema, no en el relato."
)

_INSTRUCCION_DENUNCIA = _INSTRUCCION_COMUN + (
    "\n=== DOCUMENTO: MANIFESTACIÓN DE LA DENUNCIA ===\n"
    "Esto NO es un relato tuyo: es lo que declara el denunciante, "
    "recogido por la Instrucción. Todo va atribuido a él.\n\n"
    "FORMATO OBLIGATORIO. Cada párrafo empieza por dos guiones y un "
    "espacio, y luego «Que»:\n\n"
    "-- Que sobre las 17:00 horas del día 27 observa un cargo en su "
    "cuenta que no reconoce.\n"
    "-- Que el importe asciende a 20,95 euros.\n\n"
    "Cuando el agente formula una pregunta expresa, usa esta fórmula:\n\n"
    "-- Que PREGUNTADO/A por esta Instrucción si autorizó el cargo, "
    "MANIFIESTA que NO.--\n\n"
    "Reglas del documento:\n"
    "- En PASADO o presente según lo relatado, pero siempre en tercera "
    "persona: «que observa», «que manifiesta», nunca «observé».\n"
    "- Un hecho por párrafo. Es un documento que se lee en voz alta y "
    "se firma: los párrafos largos se prestan a discusión.\n"
    "- NO escribas la fórmula de apertura ni la advertencia legal ni el "
    "cierre: se añaden aparte, literales.\n"
    "- Si el denunciante aporta datos concretos (importes, fechas, "
    "números de operación), consérvalos EXACTOS. No los redondees."
)

_INSTRUCCION_COMPARECENCIA = _INSTRUCCION_COMUN + (
    "\n=== DOCUMENTO: COMPARECENCIA DE FUNCIONARIOS ===\n"
    "Los funcionarios actuantes hacen constar lo que ellos han hecho y "
    "presenciado, para que quede unido al atestado.\n\n"
    "FORMATO OBLIGATORIO. Cada párrafo empieza por dos guiones y «Que»:\n\n"
    "-- Que sobre las 11:45 horas son comisionados por la Sala C-80 "
    "para acudir al lugar de los hechos.\n"
    "-- Que a su llegada observan…\n\n"
    "Diferencia importante con la denuncia: aquí lo que los "
    "funcionarios han COMPROBADO por sí mismos sí se afirma como hecho. "
    "Lo que les han contado terceros sigue atribuido a esos terceros.\n\n"
    "- Tercera persona del plural si son varios agentes.\n"
    "- NO escribas la fórmula de apertura ni el cierre: se añaden aparte."
)

_INSTRUCCIONES = {
    "parte": _INSTRUCCION_PARTE,
    "denuncia": _INSTRUCCION_DENUNCIA,
    "comparecencia": _INSTRUCCION_COMPARECENCIA,
}

_NOMBRES = {
    "parte": "Parte de intervención",
    "denuncia": "Denuncia de víctima",
    "comparecencia": "Comparecencia de funcionarios",
}


async def _pedir_a_la_ia(registro, mensajes, temperatura: float = 0.2) -> str:
    """Prueba proveedores de verdad, en orden, hasta que uno conteste.

    Temperatura baja (0.2) a proposito: aqui no se quiere creatividad,
    se quiere que repita el formato igual todas las veces.
    """
    ultimo = None
    for nombre_prov, nombre_mod in _PROVEEDORES:
        try:
            proveedor = registro.get(nombre_prov)
        except KeyError:
            continue
        if not proveedor.is_configured():
            continue
        try:
            return await proveedor.chat(mensajes, model=nombre_mod,
                                        temperature=temperatura)
        except (ProviderError, Exception) as e:
            ultimo = f"{nombre_prov}: {e}"
            continue
    raise HTTPException(
        502,
        "Ningún proveedor de IA ha podido con esto. "
        f"El último dijo: {ultimo or 'no hay ninguno configurado'}"
    )


@router.post("/dictar")
async def dictar(audio: UploadFile = File(...)):
    """Convierte el dictado en texto crudo, sin redactar todavía.

    Se devuelve el texto tal cual para que el agente lo LEA antes de
    redactar. Si Whisper ha entendido mal una matrícula o un importe,
    es mucho mejor verlo aquí que descubrirlo en el documento final.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(500, "GROQ_API_KEY no configurada en el servidor")

    contenido = await audio.read()
    if not contenido:
        raise HTTPException(400, "El audio ha llegado vacío")

    with clases_audio.carpeta_temporal() as tmp:
        carpeta = Path(tmp)
        sufijo = Path(audio.filename or "dictado.m4a").suffix or ".m4a"
        original = carpeta / f"entero{sufijo}"
        original.write_bytes(contenido)

        trozos = await clases_audio.partir_en_hilo(original, carpeta)
        partes: list[str] = []

        for i, trozo in enumerate(trozos, start=1):
            datos = trozo.read_bytes()
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    resp = await client.post(
                        _GROQ_TRANSCRIBE_URL,
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        files={"file": (trozo.name, datos,
                                        audio.content_type or "audio/mp4")},
                        data={"model": _MODELO_AUDIO, "response_format": "text",
                              "language": "es"},
                    )
            except httpx.RequestError as e:
                raise HTTPException(502, f"No se pudo contactar con Groq: {e}")

            if resp.status_code != 200:
                if partes:
                    partes.append(
                        f"\n\n[AVISO: el dictado se cortó aquí, en el trozo {i} "
                        f"de {len(trozos)}.]"
                    )
                    break
                raise HTTPException(502, f"Groq devolvió un error: {resp.text[:300]}")

            partes.append(resp.text.strip())

    return {"texto": "\n\n".join(partes)}


@router.post("/redactar")
async def redactar(
    tipo: str = Form(...),
    dictado: str = Form(...),
    localidad: str = Form(""),
    hora: str = Form(""),
    minutos: str = Form(""),
    dia: str = Form(""),
    mes: str = Form(""),
    anio: str = Form(""),
    agentes: str = Form(""),
    indicativo: str = Form(""),
    origen: str = Form(""),
):
    """Redacta el documento a partir del dictado ya revisado."""
    if tipo not in _INSTRUCCIONES:
        raise HTTPException(400, f"Tipo de documento desconocido: {tipo}")
    if len(dictado.strip()) < 20:
        raise HTTPException(400, "El dictado está prácticamente vacío")

    registro = ProviderRegistry(get_settings())

    contexto = ""
    if tipo == "parte":
        datos = []
        if indicativo:
            datos.append(f"Indicativo de la dotación: {indicativo}")
        if origen:
            datos.append(f"Origen de la actuación: {origen}")
        if localidad:
            datos.append(f"Municipio: {localidad}")
        if datos:
            contexto = ("=== DATOS DEL SERVICIO (úsalos si encajan en el relato) ===\n"
                        + "\n".join(datos) + "\n\n")

    cuerpo = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=_INSTRUCCIONES[tipo]),
        ChatMessage(role="user", content=contexto + "=== DICTADO DEL AGENTE ===\n" + dictado[:20000]),
    ])
    cuerpo = cuerpo.strip()

    # Las formulas fijas se pegan AQUI, en codigo, no las escribe la IA.
    if tipo == "denuncia":
        cabecera = policia_plantillas.cabecera_denuncia(
            localidad or "[LOCALIDAD]", hora or "[HH]", minutos or "[MM]",
            dia or "[DÍA]", mes or "[MES]", anio or "[AÑO]")
        documento = (f"{cabecera}\n\n"
                     f"-- COMPARECE: [Filiación del denunciante — se toma de SIDENPOL]\n\n"
                     f"{policia_plantillas.ADVERTENCIA_DENUNCIANTE}\n\n"
                     f"{cuerpo}\n\n"
                     f"{policia_plantillas.CIERRE_DENUNCIA}")
    elif tipo == "comparecencia":
        cabecera = policia_plantillas.cabecera_comparecencia(
            localidad or "[LOCALIDAD]", hora or "[HH]", minutos or "[MM]",
            dia or "[DÍA]", mes or "[MES]", anio or "[AÑO]",
            agentes or "[CARNÉ PROFESIONAL]")
        documento = (f"{cabecera}\n\n{cuerpo}\n\n"
                     f"{policia_plantillas.CIERRE_COMPARECENCIA}")
    else:
        documento = cuerpo

    return {
        "documento": documento,
        "tipo": tipo,
        "nombre": _NOMBRES[tipo],
        "generado": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
# CALIFICACION PENAL: SUGERENCIA, NUNCA CONCLUSION
# =====================================================================
_INSTRUCCION_CALIFICACION = (
    "Eres un apoyo para un agente de Policía Nacional que está "
    "redactando un documento. Te da un relato de hechos y le orientas "
    "sobre qué figuras del Código Penal español podrían encajar.\n\n"

    "ESTO ES UN BORRADOR PARA QUE UNA PERSONA LO VERIFIQUE, no un "
    "dictamen. Redacta en consecuencia.\n\n"

    "Para cada figura que propongas:\n"
    "1. Nombre del tipo penal y artículo concreto.\n"
    "2. QUÉ HECHO del relato te lleva ahí, citando la parte del relato. "
    "Si no puedes señalar el hecho concreto, no propongas la figura.\n"
    "3. Qué haría falta acreditar para que esa calificación se sostenga, "
    "y qué falta ahora mismo en el relato.\n\n"

    "REGLAS:\n"
    "- Si no estás seguro del número exacto de un artículo, DILO en vez "
    "de arriesgar una cifra. Un artículo mal citado con aplomo es peor "
    "que no citar ninguno: parece verificado y no lo está.\n"
    "- Distingue lo comprobado de lo manifestado. Si un hecho solo "
    "consta porque alguien lo dice, señálalo: la calificación descansa "
    "sobre una manifestación, no sobre una comprobación.\n"
    "- Si el relato admite varias calificaciones, dilas todas con sus "
    "diferencias, en vez de elegir una.\n"
    "- Si el relato es demasiado escaso para calificar, dilo y ya está.\n"
    "- Termina SIEMPRE con esta línea literal:\n"
    "«Esto es una orientación generada automáticamente y puede contener "
    "errores. La calificación corresponde al instructor.»"
)


@router.post("/calificar")
async def calificar(relato: str = Form(...)):
    """Sugiere posibles tipos penales sobre un relato ya redactado."""
    if len(relato.strip()) < 30:
        raise HTTPException(400, "El relato es demasiado corto para orientar nada")

    registro = ProviderRegistry(get_settings())
    texto = await _pedir_a_la_ia(registro, [
        ChatMessage(role="system", content=_INSTRUCCION_CALIFICACION),
        ChatMessage(role="user", content="=== RELATO DE LOS HECHOS ===\n" + relato[:15000]),
    ], temperatura=0.1)

    return {"calificacion": texto.strip()}


@router.get("/campos/{tipo}")
async def campos(tipo: str):
    """Qué datos pide cada documento, para pintar el formulario."""
    if tipo not in policia_plantillas.CAMPOS:
        raise HTTPException(404, "Tipo de documento desconocido")
    return {
        "campos": [
            {"id": i, "etiqueta": e, "porDefecto": d}
            for i, e, d in policia_plantillas.CAMPOS[tipo]
        ],
        "origenes": policia_plantillas.ORIGENES,
    }
