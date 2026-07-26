"""
Catalogo de tramites oficiales.

POR QUE ESTO ES UNA LISTA A MANO Y NO SE LO PREGUNTAMOS A LA IA
---------------------------------------------------------------
Lo natural seria decirle a la IA "dame la direccion donde se da de baja
un coche" y que la escribiera. Es exactamente lo que NO se puede hacer.

Si se equivoca en una letra, mandamos a una persona mayor a una web
inventada. Y resulta que copiar webs oficiales con la direccion cambiada
en un caracter es, literalmente, el negocio de los estafadores: paginas
identicas a la DGT o a la Seguridad Social que te piden el DNI y la
tarjeta. La gente a la que queremos ayudar es justo a la que mas atacan
con eso.

Asi que la IA no escribe direcciones: elige de esta lista. Si lo que
pide la persona no esta aqui, se le dice que no lo tenemos, que es una
respuesta honrada. Mandarla a un sitio dudoso, no.

Las direcciones de aqui son de organismos, no de pantallas concretas:
las rutas internas cambian cada dos por tres y un enlace roto deja a la
persona tirada. Se entra por la puerta principal y desde ahi guia el
acompañante.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tramite:
    id: str
    nombre: str                       # como lo llamaria la persona
    organismo: str
    url: str
    # Con que palabras lo pediria alguien que no sabe como se llama
    # oficialmente. "dar de baja el coche" nadie lo llama "baja temporal
    # por voluntad del titular".
    tambien: list[str] = field(default_factory=list)
    lleva: list[str] = field(default_factory=list)     # que necesita a mano
    ojo: str = ""                                      # el aviso que nadie da


CATALOGO: list[Tramite] = [
    Tramite(
        id="dgt_baja_temporal",
        nombre="Dar de baja temporal un coche",
        organismo="Dirección General de Tráfico",
        url="https://sede.dgt.gob.es/es/vehiculos/",
        tambien=["baja temporal", "dar de baja el coche", "quitar el coche de circulacion",
                 "no voy a usar el coche", "guardar el coche", "baja del vehiculo",
                 "dejar de pagar el seguro del coche"],
        lleva=["Su DNI", "El permiso de circulación del coche", "La ficha técnica"],
        ojo="Baja TEMPORAL no es lo mismo que baja definitiva. La temporal se puede "
            "deshacer cuando quiera; la definitiva es para siempre y ahí ya no hay vuelta atrás.",
    ),
    Tramite(
        id="dgt_informe_vehiculo",
        nombre="Ver los datos o las multas de un coche",
        organismo="Dirección General de Tráfico",
        url="https://sede.dgt.gob.es/es/",
        tambien=["multas", "tengo multas", "puntos del carnet", "cuantos puntos tengo",
                 "informe del vehiculo", "itv del coche"],
        lleva=["Su DNI", "La matrícula"],
    ),
    Tramite(
        id="dni_cita",
        nombre="Pedir cita para renovar el DNI o el pasaporte",
        organismo="Policía Nacional",
        url="https://www.citapreviadnie.es/",
        tambien=["renovar el dni", "cita dni", "se me caduca el dni", "hacer el pasaporte",
                 "renovar el carnet de identidad"],
        lleva=["Su DNI (aunque esté caducado)"],
        ojo="En el reverso del DNI, debajo de donde pone EQUIPO, hay un código que le "
            "van a pedir. Y si su DNI es permanente, tendrá que escribir esa palabra "
            "en vez de una fecha.",
    ),
    Tramite(
        id="ss_cita",
        nombre="Pedir cita en la Seguridad Social",
        organismo="Seguridad Social",
        url="https://www.seg-social.es/wps/portal/wss/internet/CitaPrevia",
        tambien=["cita seguridad social", "cita para la pension", "ir a la seguridad social",
                 "cita en el inss"],
        lleva=["Su DNI", "Su número de la Seguridad Social si lo tiene"],
    ),
    Tramite(
        id="ss_vida_laboral",
        nombre="Pedir la vida laboral",
        organismo="Seguridad Social",
        url="https://www.seg-social.es/wps/portal/wss/internet/Inicio",
        tambien=["vida laboral", "informe de vida laboral", "años cotizados",
                 "cuanto he cotizado", "mis años trabajados"],
        lleva=["Su DNI", "Un móvil donde recibir un mensaje"],
    ),
    Tramite(
        id="ss_pension",
        nombre="Cosas de la pensión",
        organismo="Seguridad Social",
        url="https://www.seg-social.es/wps/portal/wss/internet/Pensionistas",
        tambien=["mi pension", "cuando me puedo jubilar", "jubilacion",
                 "certificado de la pension", "cuanto voy a cobrar"],
        lleva=["Su DNI"],
    ),
    Tramite(
        id="aeat_renta",
        nombre="La declaración de la renta",
        organismo="Agencia Tributaria (Hacienda)",
        url="https://sede.agenciatributaria.gob.es/",
        tambien=["la renta", "declaracion", "hacienda", "borrador de la renta",
                 "me toca pagar a hacienda", "devolucion de hacienda"],
        lleva=["Su DNI", "El número de referencia o la Cl@ve"],
        ojo="Hacienda NUNCA le va a escribir un correo o un mensaje pidiéndole datos "
            "de su banco. Si le llega algo así, es un timo.",
    ),
    Tramite(
        id="salud_cita",
        nombre="Pedir cita con el médico",
        organismo="Su comunidad autónoma",
        url="https://www.sanidad.gob.es/ciudadanos/centrosCA.do",
        tambien=["cita medico", "cita con el medico de cabecera", "centro de salud",
                 "pedir hora en el ambulatorio"],
        lleva=["Su tarjeta sanitaria"],
        ojo="Esto lo lleva cada comunidad por su cuenta, así que primero hay que "
            "elegir dónde vive usted.",
    ),
    Tramite(
        id="sepe_paro",
        nombre="Cosas del paro",
        organismo="SEPE",
        url="https://www.sepe.es/",
        tambien=["el paro", "cobrar el paro", "sellar el paro", "prestacion por desempleo",
                 "renovar la demanda"],
        lleva=["Su DNI"],
    ),
    Tramite(
        id="catastro",
        nombre="Datos de una casa o un terreno",
        organismo="Catastro",
        url="https://www.sedecatastro.gob.es/",
        tambien=["catastro", "referencia catastral", "datos de mi casa", "mi piso",
                 "metros de mi vivienda"],
        lleva=["Su DNI", "La dirección de la casa"],
    ),
    Tramite(
        id="carpeta_ciudadana",
        nombre="Ver todos sus papeles con la Administración",
        organismo="Gobierno de España",
        url="https://carpetaciudadana.gob.es/",
        tambien=["mis datos", "que papeles tengo", "mis tramites", "carpeta ciudadana",
                 "que me consta"],
        lleva=["Cl@ve o certificado digital"],
    ),
    Tramite(
        id="certificado_fnmt",
        nombre="Sacar el certificado digital",
        organismo="FNMT",
        url="https://www.sede.fnmt.gob.es/certificados/persona-fisica",
        tambien=["certificado digital", "firma digital", "certificado electronico"],
        lleva=["Su DNI", "Un ordenador (en el móvil no se puede terminar)"],
        ojo="Esto NO se puede terminar desde el móvil: hace falta un ordenador porque "
            "hay que instalar un programa. Y hay que hacerlo todo en el mismo ordenador.",
    ),
    Tramite(
        id="clave",
        nombre="Registrarse en Cl@ve",
        organismo="Gobierno de España",
        url="https://clave.gob.es/",
        tambien=["clave", "clave pin", "darme de alta en clave", "identificarme por internet"],
        lleva=["Su DNI", "Un móvil donde recibir mensajes"],
    ),
    Tramite(
        id="padron",
        nombre="Empadronarse o pedir el certificado de empadronamiento",
        organismo="Su ayuntamiento",
        url="https://administracion.gob.es/pag_Home/Tu-espacio-europeo/derechos-obligaciones/ciudadanos/residencia/empadronamiento.html",
        tambien=["empadronarme", "padron", "certificado de empadronamiento", "volante de empadronamiento"],
        lleva=["Su DNI", "Un recibo de la luz o del agua de su casa"],
        ojo="Esto lo lleva su ayuntamiento, así que puede que tenga que ir en persona.",
    ),
]


def resumen_para_ia() -> str:
    """La lista tal como la ve la IA para poder elegir."""
    lineas = []
    for t in CATALOGO:
        alias = "; ".join(t.tambien[:6])
        lineas.append(f"- {t.id} | {t.nombre} ({t.organismo}) | la gente lo pide así: {alias}")
    return "\n".join(lineas)


def buscar(id_tramite: str) -> Tramite | None:
    for t in CATALOGO:
        if t.id == id_tramite:
            return t
    return None
