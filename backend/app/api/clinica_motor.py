"""
EL MOTOR DE RAZONAMIENTO DEL LABERINTO CLINICO.

POR QUE ESTO ES CODIGO Y NO INTELIGENCIA ARTIFICIAL

Si a un modelo de lenguaje le pides "dame el porcentaje de probabilidad de
esta patologia", contesta un numero. Siempre. Con dos decimales y mucha
seguridad. Y ese numero no significa nada: no ha calculado nada, lo ha
escrito porque le has pedido un numero.

En una app de estudio de medicina eso no es un defecto estetico. Un "72%"
inventado parece MAS fiable que un "probable" honesto, y ademas cambia de
una sesion a otra sin motivo. Un alumno no puede aprender a razonar con una
cosa que no razona igual dos veces seguidas.

Asi que aqui la puntuacion la calcula el codigo, con reglas fijas que se
pueden leer, discutir y corregir. La IA no entra en esta parte. La IA
explica; el motor decide.

Efecto secundario muy util: navegar casos no cuesta ni una llamada. Se puede
estar una hora dando vueltas al diferencial sin gastar nada.

COMO PUNTUA

Cada patologia declara que hallazgos espera y cuanto pesa cada uno:

    tipico       +3   casi siempre esta
    frecuente    +2   aparece a menudo
    posible      +1   compatible, no caracteristico
    atipico      -2   raro en esta patologia
    incompatible      la mata directamente

LA AUSENCIA TAMBIEN INFORMA

Esto es lo que separa un buscador de una herramienta de diagnostico
diferencial. "No tiene fiebre" no es la falta de un dato: es un dato. Si un
hallazgo tipico de una patologia se ha descartado expresamente, esa
patologia baja.

Por eso cada hallazgo tiene tres estados posibles y no dos: presente,
ausente, y sin preguntar. Los dos primeros puntuan; el tercero no.

EL PORCENTAJE, DICHO CON HONESTIDAD

Lo que se muestra es el peso relativo de cada patologia frente a las demas
que siguen vivas. NO es una probabilidad clinica. Sirve para ordenar y para
estudiar el patron tipico. No sirve para decidir nada sobre un paciente, y
la app lo dice en pantalla, no en letra pequeña.
"""
from __future__ import annotations

PESOS = {
    # El signo que cierra el diagnostico. Pesa mucho mas que un tipico
    # porque no dice "encaja": dice "es esto".
    "patognomonico": 8,
    "tipico": 3,
    "frecuente": 2,
    "posible": 1,
    "atipico": -2,
}

# Lo que resta la AUSENCIA confirmada de un hallazgo, segun lo esperable que
# fuera. Que falte algo tipico pesa; que falte algo meramente posible no
# dice casi nada -y por eso no resta-.
PESOS_AUSENCIA = {
    # QUE FALTE UN PATOGNOMONICO NO RESTA NADA. Y esto no es un descuido.
    #
    # Un signo patognomonico es especifico, no sensible: si esta, cierra el
    # diagnostico; si no esta, no dice absolutamente nada, porque la mayoria
    # de los enfermos no lo tienen. Restar por su ausencia seria descartar
    # una meningitis por no ver petequias.
    "patognomonico": 0,
    "tipico": -3,
    "frecuente": -1,
    "posible": 0,
    "atipico": 0,
}

ETIQUETAS = {
    "patognomonico": "patognomónico",
    "tipico": "tipico",
    "frecuente": "frecuente",
    "posible": "posible",
    "atipico": "atipico",
}


def _texto_motivo(nombre: str, relacion: str, estado: str) -> str:
    if estado == "presente":
        return f"{nombre} ({ETIQUETAS.get(relacion, relacion)})"
    return f"sin {nombre} ({ETIQUETAS.get(relacion, relacion)})"


def _evaluar_una(pat: dict, presentes: dict, edad, sexo) -> dict:
    """
    Puntua UNA patologia contra los datos del caso.

    Devuelve siempre los motivos, incluso cuando descarta: el objetivo de la
    app es que se vea POR QUE se cae algo, no solo que se ha caido. Un
    descarte sin explicacion no enseña nada.
    """
    puntos = 0
    motivos: list[dict] = []
    descartada_por: str | None = None

    esperados = pat.get("hallazgos", {})

    for hid, estado in presentes.items():
        relacion = esperados.get(hid)
        if relacion is None:
            continue

        if relacion == "incompatible":
            if estado == "presente":
                descartada_por = hid
                motivos.append({"hallazgo": hid, "puntos": 0, "estado": estado,
                                "relacion": relacion, "mata": True})
            continue

        tabla = PESOS if estado == "presente" else PESOS_AUSENCIA
        p = tabla.get(relacion, 0)
        if p:
            puntos += p
            motivos.append({"hallazgo": hid, "puntos": p, "estado": estado,
                            "relacion": relacion, "mata": False})

    # La edad y el sexo MODULAN, no proponen.
    #
    # Al probarlo salia que con solo escribir "varon, 68 años" ya aparecia una
    # leucemia al 15%, sin un solo dato clinico: la franja de edad encajaba y
    # sumaba. Eso es ruido puro, y encima del peor tipo, porque coloca
    # diagnosticos graves delante de los ojos sin ningun motivo.
    #
    # La regla que lo arregla: la edad y el sexo solo puntuan si la patologia
    # ya tiene un apoyo clinico REAL. Ser mayor no es un sintoma.
    #
    # Al principio bastaba con una coincidencia cualquiera, y con la base
    # pequeña colaba. Con sesenta patologias ya no: en un caso de proteina
    # monoclonal aparecian una malaria y una endocarditis empatadas con el
    # mieloma, cada una apoyada en un solo "anemia" mas el premio de la
    # edad. Por eso el umbral es 4 y no 1: un unico hallazgo tipico se
    # queda corto, hacen falta dos coincidencias o una muy fuerte.
    hay_apoyo_clinico = puntos >= _APOYO_MINIMO_PARA_EDAD

    franja = pat.get("edad_tipica")
    if hay_apoyo_clinico and isinstance(edad, (int, float)) and franja:
        lo, hi = franja
        if lo <= edad <= hi:
            puntos += 2
            motivos.append({"hallazgo": "_edad", "puntos": 2, "estado": "presente",
                            "relacion": "franja tipica", "mata": False})
        else:
            fuera = lo - edad if edad < lo else edad - hi
            castigo = -3 if fuera > 20 else -1
            puntos += castigo
            motivos.append({"hallazgo": "_edad", "puntos": castigo, "estado": "presente",
                            "relacion": "fuera de la franja tipica", "mata": False})

    # Sexo. Aqui si cabe el descarte, pero solo cuando es anatomicamente
    # imposible ("solo_varon" / "solo_mujer"). Un simple predominio se trata
    # como lo que es: una tendencia, no una regla.
    s = pat.get("sexo")
    if sexo in ("varon", "mujer") and s:
        if s == "solo_varon" and sexo != "varon":
            descartada_por = "_sexo"
        elif s == "solo_mujer" and sexo != "mujer":
            descartada_por = "_sexo"
        elif not hay_apoyo_clinico:
            pass
        elif s == "predomina_varon":
            d = 1 if sexo == "varon" else -1
            puntos += d
            motivos.append({"hallazgo": "_sexo", "puntos": d, "estado": "presente",
                            "relacion": "predominio por sexo", "mata": False})
        elif s == "predomina_mujer":
            d = 1 if sexo == "mujer" else -1
            puntos += d
            motivos.append({"hallazgo": "_sexo", "puntos": d, "estado": "presente",
                            "relacion": "predominio por sexo", "mata": False})

    return {
        "id": pat["id"],
        "nombre": pat["nombre"],
        "sistemas": pat.get("sistemas", []),
        "puntos": puntos,
        "descartada": descartada_por is not None,
        "descartada_por": descartada_por,
        "motivos": motivos,
    }


def evaluar(datos: list[dict], patologias: list[dict], previas: dict | None = None) -> dict:
    """
    Evalua el caso entero.

    `datos` es la lista de lo que se ha ido metiendo:
        [{"id": "fiebre", "estado": "presente"},
         {"id": "rigidez_nuca", "estado": "ausente"},
         {"id": "_edad", "valor": 68},
         {"id": "_sexo", "valor": "varon"}]

    `previas` es el mapa {id_patologia: puntos} de la evaluacion anterior, y
    sirve solo para poder pintar la flechita de si algo sube o baja. Es
    opcional: sin ella todo sale sin tendencia.
    """
    presentes: dict[str, str] = {}
    edad = None
    sexo = None
    for d in datos or []:
        i = d.get("id")
        if i == "_edad":
            try:
                edad = float(d.get("valor"))
            except (TypeError, ValueError):
                edad = None
        elif i == "_sexo":
            sexo = d.get("valor")
        elif i:
            presentes[i] = d.get("estado", "presente")

    filas = [_evaluar_una(p, presentes, edad, sexo) for p in patologias]

    vivas = [f for f in filas if not f["descartada"]]
    muertas = [f for f in filas if f["descartada"]]

    # El porcentaje se reparte solo entre las vivas y solo contando puntos
    # positivos. Una patologia con puntuacion negativa sigue en la lista
    # -no se ha descartado formalmente- pero no puede ocupar cuota.
    #
    # Y ademas se guarda una RESERVA para lo que todavia no se sabe.
    #
    # Sin ella pasaba esto: metias dos datos y la primera opcion salia al
    # 100%, simplemente porque era la unica con puntos. Un 100% con dos datos
    # es mentira, y de la peor especie: cierra el razonamiento justo cuando
    # deberia estar abierto. La reserva baja sola segun se van metiendo
    # datos, y a partir de seis desaparece.
    reserva = max(0, (_DATOS_PARA_CONFIAR - len(presentes))) * 2

    # LA COLA DE RUIDO NO COMPITE.
    #
    # Al pasar de 12 a 44 patologias aparecio un efecto feo: un caso de
    # dengue de libro se quedaba en el 14%, no porque hubiera dudas, sino
    # porque otras diecinueve patologias coincidian en "fiebre" y entre
    # todas se llevaban media tarta. El orden era correcto y la cifra
    # enseñaba algo falso -que la cosa estaba muy repartida cuando no lo
    # estaba-, y el problema iba a empeorar con cada tanda nueva.
    #
    # Coincidir en un dato generico no es ser candidata. Solo reparten
    # porcentaje las que llegan a una fraccion de la mejor; el resto se
    # quedan en la lista, visibles, pero marcadas como que solo rozan el
    # patron.
    mejor = max((f["puntos"] for f in vivas), default=0)
    corte = max(_MINIMO_CANDIDATA, mejor * _FRACCION_CANDIDATA) if mejor > 0 else 0
    principales = [f for f in vivas if f["puntos"] >= corte and f["puntos"] > 0]
    if not principales:  # nadie llega al corte: compiten todas las positivas
        principales = [f for f in vivas if f["puntos"] > 0]
    en_juego = {f["id"] for f in principales}

    total = sum(f["puntos"] for f in principales) + reserva
    for f in vivas:
        f["menor"] = f["puntos"] > 0 and f["id"] not in en_juego
        peso = f["puntos"] if f["id"] in en_juego else 0
        f["porcentaje"] = round(100 * max(0, peso) / total) if total else 0
        ant = (previas or {}).get(f["id"])
        f["tendencia"] = 0 if ant is None else (1 if f["puntos"] > ant else (-1 if f["puntos"] < ant else 0))
    for f in muertas:
        f["porcentaje"] = 0
        f["tendencia"] = 0

    vivas.sort(key=lambda f: (-f["puntos"], f["nombre"]))
    muertas.sort(key=lambda f: f["nombre"])

    hay_datos = bool(presentes)

    return {
        "vivas": vivas,
        "descartadas": muertas,
        "sistemas": _estado_sistemas(vivas, muertas, patologias, hay_datos),
        "puntos": {f["id"]: f["puntos"] for f in filas},
        "hay_datos": hay_datos,
        # Cuanto del reparto sigue en el aire. Se enseña en pantalla como
        # "faltan datos": es informacion, no un hueco que disimular.
        "sin_concretar": round(100 * reserva / total) if total else 100,
        "datos_metidos": len(presentes),
        "menores": sum(1 for f in vivas if f.get("menor")),
    }


_UMBRAL_EN_JUEGO = 10  # porcentaje
_DATOS_PARA_CONFIAR = 6  # por debajo de esto, parte del peso queda en reserva
_FRACCION_CANDIDATA = 0.35  # hay que llegar a este trozo de la mejor para repartir
_MINIMO_CANDIDATA = 5       # y a esto en absoluto, para no premiar una coincidencia suelta
_APOYO_MINIMO_PARA_EDAD = 4  # puntos clinicos antes de que la edad y el sexo cuenten


def _estado_sistemas(vivas, muertas, patologias, hay_datos: bool) -> list[dict]:
    """
    El estado de un sistema se decide por su MEJOR patologia, no por cuantas
    le quedan vivas.

    La primera version contaba supervivientes, y salia que neurologia seguia
    "en juego" en un caso de adenopatias solo porque a la migraña nadie la
    habia matado formalmente. Tecnicamente cierto e inutil: lo que quieres
    saber de un sistema no es si le queda algo, es si le queda algo que
    importe.
    """
    todos: dict[str, dict] = {}
    for p in patologias:
        for s in p.get("sistemas", []):
            todos.setdefault(s, {"sistema": s, "vivas": 0, "mejor": 0, "total": 0})
            todos[s]["total"] += 1
    for f in vivas:
        for s in f["sistemas"]:
            if s in todos:
                todos[s]["vivas"] += 1
                todos[s]["mejor"] = max(todos[s]["mejor"], f["porcentaje"])

    salida = []
    for s, d in todos.items():
        if not hay_datos:
            estado = "sin_datos"
        elif d["vivas"] == 0:
            estado = "descartado"
        elif d["mejor"] >= _UMBRAL_EN_JUEGO:
            estado = "en_juego"
        else:
            estado = "poco_probable"
        salida.append({"sistema": s, "estado": estado, "mejor": d["mejor"],
                       "vivas": d["vivas"], "total": d["total"]})
    orden = {"en_juego": 0, "poco_probable": 1, "sin_datos": 2, "descartado": 3}
    salida.sort(key=lambda x: (orden[x["estado"]], -x["mejor"], x["sistema"]))
    return salida


def sugerir(datos: list[dict], patologias: list[dict], cuantos: int = 3,
            costes: dict[str, int] | None = None) -> list[str]:
    """
    QUE CONVIENE PREGUNTAR AHORA.

    Esta es la parte que mas se parece a tener a alguien al lado. En vez de
    esperar a que se te ocurra el dato que lo aclara todo, se calcula.

    La idea: un hallazgo es util si SEPARA a las patologias que ahora mismo
    van en cabeza. Preguntar algo que todas comparten no aclara nada, por
    mucho que sea muy tipico de todas ellas. Lo que discrimina es aquello en
    lo que las candidatas NO se parecen.

    Se mide como la dispersion del peso de ese hallazgo entre las
    candidatas, ponderada por lo arriba que va cada una. Y sin IA: es
    aritmetica sobre la base.

    Con un matiz que hubo que añadir despues de probarlo: la primera version
    proponia mirar el LCR como primera pregunta ante una cefalea. Discrimina
    muchisimo, si -y es exactamente lo que ningun medico hace primero-. Asi
    que la utilidad se divide por lo que cuesta averiguarlo, y lo barato sale
    antes. Una prueba invasiva solo se propone cuando de verdad compensa.
    """
    r = evaluar(datos, patologias)
    ya = {d.get("id") for d in (datos or [])}
    # Hacen falta al menos tres candidatas para que "separar" signifique
    # algo. Con una sola no hay nada que comparar y no salia ninguna
    # sugerencia -justo al principio del caso, que es cuando mas falta
    # hace-. Si no hay suficientes con puntos, se completa con las
    # siguientes de la lista.
    candidatas = [f for f in r["vivas"] if f["puntos"] > 0][:6]
    if len(candidatas) < 3:
        ya_estan = {f["id"] for f in candidatas}
        candidatas += [f for f in r["vivas"] if f["id"] not in ya_estan][:6 - len(candidatas)]
    if not candidatas:
        return []

    porid = {p["id"]: p for p in patologias}
    pesototal = sum(max(1, f["puntos"]) for f in candidatas) or 1

    puntuacion: dict[str, float] = {}
    for f in candidatas:
        peso_pat = max(1, f["puntos"]) / pesototal
        for hid, rel in porid[f["id"]].get("hallazgos", {}).items():
            if hid in ya:
                continue
            v = -6 if rel == "incompatible" else PESOS.get(rel, 0)
            puntuacion.setdefault(hid, 0.0)
            puntuacion[hid] += v * peso_pat

    # Dispersion: para cada hallazgo, cuanto se separan las candidatas entre
    # si. Se aproxima con la media de las diferencias al valor medio.
    dispersion: dict[str, float] = {}
    for hid in puntuacion:
        valores = []
        for f in candidatas:
            rel = porid[f["id"]].get("hallazgos", {}).get(hid)
            valores.append(-6 if rel == "incompatible" else PESOS.get(rel, 0))
        media = sum(valores) / len(valores)
        dispersion[hid] = sum(abs(v - media) for v in valores) / len(valores)

    costes = costes or {}
    utilidad = {h: d / (costes.get(h, 1) ** 0.5) for h, d in dispersion.items() if d > 0}
    mejores = sorted(utilidad.items(), key=lambda kv: -kv[1])
    return [h for h, _ in mejores][:cuantos]
