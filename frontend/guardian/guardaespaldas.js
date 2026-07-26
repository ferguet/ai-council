/* =====================================================================
   MODO GUARDAESPALDAS
   =====================================================================
   Se inyecta en cualquier tienda o web normal. Aqui no hay ningun
   tramite que completar, asi que no guia: VIGILA.

   Nace de una observacion de campo: a las personas mayores no les
   arruina el dia no encontrar un boton. Les arruina el mes descubrir
   que llevan seis meses pagando una suscripcion que nunca pidieron, o
   un seguro que venia marcado de fabrica en la pantalla de pagar.

   Lo bueno de las trampas es que casi todas tienen la misma forma en
   todas las tiendas: una casilla ya marcada, un precio con "al mes"
   escondido, un boton gigante de aceptar frente a uno gris de
   rechazar. Por eso esto NO necesita un guion por cada web: reconoce
   la forma de la trampa, no la tienda.

   Lo que NO hace, a proposito:
     - No pulsa nada por la persona. Ni desmarca casillas. Avisa y ya:
       la decision es suya, no mia.
     - No lee ni guarda lo que escribe.
     - No manda nada a ningun sitio.
   ===================================================================== */
(function () {
  if (window.__guardaViva) return;
  window.__guardaViva = true;

  function visible(e) {
    if (!e || !e.offsetParent) return false;
    var r = e.getBoundingClientRect();
    return r.width > 6 && r.height > 6 && r.top < window.innerHeight * 3;
  }
  function limpio(t) { return (t || '').replace(/\s+/g, ' ').trim(); }

  /* Texto que rodea a un elemento: para entender de que va */
  function entorno(e, saltos) {
    var t = '', n = e;
    for (var i = 0; i < (saltos || 3) && n; i++) { n = n.parentElement; if (n) t = limpio(n.textContent); }
    return t.toLowerCase();
  }

  /* Busca un boton o enlace visible cuyo texto contenga alguna palabra */
  function botonCon2(palabras) {
    var t = [].slice.call(document.querySelectorAll('button,a,input[type=submit],input[type=button]'));
    for (var i = 0; i < t.length; i++) {
      if (!visible(t[i])) continue;
      var s = limpio(t[i].textContent || t[i].value).toLowerCase();
      if (s.length > 60) continue;                 // parrafos, no botones
      for (var j = 0; j < palabras.length; j++) {
        if (s.indexOf(palabras[j]) !== -1) return t[i];
      }
    }
    return null;
  }

  /* ---------------------------------------------------------------
     LAS TRAMPAS
     Ordenadas por lo que cuesta caer en ellas. Una casilla marcada que
     te cobra todos los meses es mucho peor que un aviso de cookies.
     --------------------------------------------------------------- */

  var PAGO = /suscrip|renovaci[oó]n autom|al mes|\/ ?mes|mensual|cada mes|anual|al a[ñn]o|prueba gratis|primer mes|periodo de prueba|seguro|protecci[oó]n|garant[ií]a extendida|cancelaci[oó]n flexible|premium/i;
  var PRECIO = /\d+[.,]\d{2}\s*€|€\s*\d+[.,]\d{2}|\d+\s*euros/i;

  function trampas() {
    var lista = [];

    /* 1. Casillas YA MARCADAS que tienen que ver con dinero.
          Es la trampa mas cara: nadie desmarca lo que ya viene puesto. */
    var cajas = [].slice.call(document.querySelectorAll('input[type=checkbox]'));
    for (var i = 0; i < cajas.length; i++) {
      var c = cajas[i];
      if (!c.checked || !visible(c)) continue;
      var ent = entorno(c, 3);
      if (PAGO.test(ent)) {
        lista.push({
          el: c, gravedad: 3, corto: 'Casilla marcada',
          voz: 'Atencion a esto. Hay una casilla ya marcada que usted no ha tocado, y tiene que ver con un pago. ' +
               'Muchas tiendas las dejan puestas a proposito para colarle un seguro o una suscripcion. ' +
               'Lea lo que pone al lado y, si no lo ha pedido, quitele la marca usted mismo. Yo no se la voy a quitar: es su decision.'
        });
      }
    }

    /* 2. Un precio con "al mes" o "renovacion automatica" cerca.
          Creen que compran una cosa y estan contratando una cuota. */
    var trozos = [].slice.call(document.querySelectorAll('p,span,div,li,label,td,strong,h2,h3'));
    for (var j = 0; j < trozos.length; j++) {
      var z = trozos[j];
      if (z.children.length > 0 || !visible(z)) continue;
      var t = limpio(z.textContent);
      if (t.length < 6 || t.length > 180) continue;
      if (PRECIO.test(t) && /al mes|\/ ?mes|mensual|cada mes|renovaci[oó]n autom|al a[ñn]o/i.test(t)) {
        lista.push({
          el: z, gravedad: 2, corto: 'Le cobran cada mes',
          voz: 'Cuidado, esto no es un pago de una vez. Fijese: pone un precio y al lado dice que es al mes. ' +
               'Si sigue adelante se lo van a cobrar todos los meses hasta que usted lo cancele. ' +
               'Si lo que queria era comprar una cosa suelta, esto no es lo que busca.'
        });
        break;
      }
    }

    /* 3. "Gratis" que luego se cobra solo. */
    for (var k = 0; k < trozos.length; k++) {
      var z2 = trozos[k];
      if (z2.children.length > 0 || !visible(z2)) continue;
      var t2 = limpio(z2.textContent);
      if (t2.length < 8 || t2.length > 200) continue;
      if (/prueba gratis|gratis durante|primer mes gratis|30 d[ií]as gratis|gratis el primer/i.test(t2)) {
        lista.push({
          el: z2, gravedad: 2, corto: 'Gratis solo al principio',
          voz: 'Ojo con la palabra gratis de aqui. Es gratis solo los primeros dias. Cuando se acaben, empiezan a cobrarle solos, sin avisar y sin volver a preguntarle. ' +
               'Si acepta esto, apunte en el calendario cuando termina.'
        });
        break;
      }
    }

    /* 0. EL PUNTO DE NO RETORNO: el boton que cobra de verdad.
     *
     * Va el primero de todos porque es el unico momento del que no se
     * vuelve. Todo lo demas se puede deshacer; esto no. Muchas personas
     * mayores no distinguen "meter en la cesta" de "pagar", porque los
     * botones se parecen y estan cerca.
     */
    var botonPagar = botonCon2(['comprar ahora', 'comprar con 1 clic', 'comprar con un clic',
      'realizar el pedido', 'realizar pedido', 'finalizar compra', 'finalizar pedido',
      'pagar ahora', 'confirmar pedido', 'confirmar compra', 'tramitar pedido']);
    if (botonPagar) {
      lista.push({
        el: botonPagar, gravedad: 4, corto: 'Esto ya es pagar',
        voz: 'Pare un momento. Este boton no es para mirar ni para guardar: en cuanto lo pulse, ' +
             'la compra esta hecha y le cobran el dinero. No hay una pantalla mas para confirmar. ' +
             'Si queria seguir mirando o pensarselo, este no es el boton. Si esta seguro, adelante.'
      });
    }

    /* 0.bis Elegir forma de pago. Es el paso anterior al cobro y ahi se
     * cuelan cosas: pagar a plazos con intereses, tarjetas de credito de
     * la propia tienda, financiaciones... */
    // Antes esto exigia que en la pagina saliera "bizum" Y "tarjeta" Y
    // "forma de pago" a la vez, y casi nunca se cumplian las tres: el
    // aviso no saltaba nunca. Ahora basta con que se hable de elegir
    // pago, o que aparezcan dos formas de pago juntas.
    var textoPago = limpio(document.body.textContent).slice(0, 9000);
    // Me pase de listo al aflojar esto: con que en la pagina saliera
    // "tarjeta" y "paypal" en cualquier sitio ya avisaba, y en una
    // tienda esas palabras salen en TODAS las pantallas. Resultado: el
    // aviso permanente que has visto. Ahora hace falta que la pantalla
    // este pidiendo elegir pago de verdad, no que la palabra aparezca.
    var hablaDePagar = /forma de pago|m[eé]todo de pago|formas de pago|elige c[oó]mo pagar|c[oó]mo quieres pagar|selecciona.{0,20}pago/i.test(textoPago);
    var opcionDePago = !!botonCon2(['pagar con tarjeta', 'pagar con bizum', 'pagar con paypal',
                                    'contrarreembolso', 'a plazos', 'financiar']);
    if (hablaDePagar && opcionDePago) {
      var aPlazos = botonCon2(['a plazos', 'financiar', 'paga en 3', 'paga en 4', 'aplazar', 'financiaci']);
      lista.push({
        el: aPlazos, gravedad: 3, corto: 'Cómo va a pagar',
        voz: 'Le estan preguntando como quiere pagar. Con tarjeta o con bizum, el dinero sale de su cuenta y se acabo. ' +
             'Pero si elige pagar a plazos o financiar, eso es un prestamo: le van a cobrar todos los meses y normalmente con intereses. ' +
             'Si puede pagarlo de una vez, salga mas barato.'
      });
    }

    /* 0.ter Meter en la cesta: NO es peligroso, pero mucha gente cree
     * que ya ha comprado y se queda tranquila, o al reves, cree que
     * comprando es solo mirar. Un aviso corto y tranquilizador. */
    var botonCesta = botonCon2(['añadir a la cesta', 'anadir a la cesta', 'añadir al carrito',
      'agregar al carrito', 'añadir a la bolsa']);
    if (botonCesta && !botonPagar) {
      lista.push({
        el: botonCesta, gravedad: 1, corto: 'Esto no cobra',
        voz: 'Tranquilo, este boton no le cobra nada. Solo guarda el articulo en una lista, como el carro del supermercado. ' +
             'Todavia puede quitarlo o dejarlo ahi. El cobro es mas adelante y yo se lo avisare.'
      });
    }

    /* 0.quater "Regalo", "premio", "recogelo en la aplicacion".
     * Tipico de Temu y similares: no es un regalo, es el anzuelo para
     * que instale la app y para que compre. */
    var botonRegalo = botonCon2(['recoge tu regalo', 'obtener regalo', 'obtenlo en la aplicaci',
      'reclama tu premio', 'has ganado', 'gira la ruleta', 'consigue tu regalo', 'abrir en la app']);
    if (botonRegalo) {
      lista.push({
        el: botonRegalo, gravedad: 3, corto: 'No es un regalo',
        voz: 'Eso que le ofrecen no es un regalo de verdad. Es el gancho para que instale su aplicacion y para que acabe comprando. ' +
             'Nadie regala nada por entrar en una pagina. Puede seguir mirando sin tocar eso: no se pierde nada.'
      });
    }

    /* 0.sexies TE MANDAN A LA TIENDA DE APLICACIONES.
     * Muchas paginas empujan a instalar su app porque dentro pueden
     * hacer lo que quieran: mandar avisos a todas horas, ver mas datos
     * del movil y, sobre todo, quitarse de encima al guardaespaldas.
     * Dentro de su aplicacion nosotros ya no protegemos nada. */
    var aTienda = null;
    var enlaces = [].slice.call(document.querySelectorAll('a'));
    for (var y = 0; y < enlaces.length; y++) {
      var lk = enlaces[y];
      if (!visible(lk)) continue;
      var destino = (lk.getAttribute('href') || '').toLowerCase();
      var txtLk = limpio(lk.textContent).toLowerCase();
      if (/play\.google|apps\.apple|market:\/\//.test(destino) ||
          /descargar la app|descarga la app|instalar la app|abrir en la app|cont[ií]nua en la app/.test(txtLk)) {
        aTienda = lk; break;
      }
    }
    if (!aTienda) aTienda = botonCon2(['descargar la app', 'instalar la aplicaci', 'abrir en la app', 'continuar en la app']);
    if (aTienda) {
      // Solo si te lo estan poniendo delante: grande y en pantalla.
      var rT = aTienda.getBoundingClientRect();
      var teLoMeten = rT.top < window.innerHeight && rT.bottom > 0 &&
                      rT.width > 90 && rT.height > 28;
      if (!teLoMeten) aTienda = null;
    }
    if (aTienda) {
      lista.push({
        el: aTienda, gravedad: 3, corto: 'No hace falta la app',
        voz: 'Le estan empujando a instalar su aplicacion. No le hace ninguna falta: todo lo que quiere hacer se puede hacer aqui mismo. ' +
             'Y ojo, que dentro de su aplicacion yo ya no puedo avisarle de nada. Aqui estamos mejor.'
      });
    }

    /* 3.bis PEDIR OFERTA / PRESUPUESTO / INFORMACION / DONAR.
     *
     * Visto en la web de un fabricante de coches: das a "pedir oferta" y
     * la app no decia nada, porque tecnicamente no hay ningun cobro. Pero
     * para la persona si pasa algo importante: sus datos se van a una
     * empresa y a partir de ahi la van a llamar por telefono a vender.
     * Eso, con gente mayor, es la puerta de entrada de muchos timos.
     * No hay que impedirlo -a lo mejor si quiere la oferta-, hay que
     * decirle claramente lo que va a pasar.
     */
    var camposPersonales = 0, pideTelefono = false;
    var entradas = [].slice.call(document.querySelectorAll('input,textarea'));
    for (var n = 0; n < entradas.length; n++) {
      var ee = entradas[n];
      if (!visible(ee) || ee.type === 'hidden') continue;
      var ctxE = (ee.name + ' ' + ee.id + ' ' + ee.placeholder + ' ' + entorno(ee, 2)).toLowerCase();
      if (/nombre|apellido|correo|email|e-mail|tel[eé]fono|movil|m[oó]vil|c[oó]digo postal|direcci[oó]n/.test(ctxE)) {
        camposPersonales++;
        if (/tel[eé]fono|movil|m[oó]vil/.test(ctxE)) pideTelefono = true;
      }
    }
    var botonComercial = botonCon2(['pedir oferta', 'solicitar oferta', 'solicita tu oferta',
      'pedir presupuesto', 'solicitar informaci', 'quiero informaci', 'me interesa',
      'contactar', 'te llamamos', 'donar', 'donaci']);
    if (camposPersonales >= 2 && botonComercial) {
      var esDonar = /donar|donaci/i.test(limpio(botonComercial.textContent || ''));
      lista.push({
        el: botonComercial, gravedad: 2,
        corto: esDonar ? 'Le van a cobrar' : 'Le van a llamar',
        voz: esDonar
          ? 'Ojo, esto es una donacion: va a dar dinero suyo. Antes de seguir, mire bien si es una sola vez o si se lo van a cobrar todos los meses, ' +
            'porque muchas veces viene puesto lo segundo sin que se vea. Y asegurese de que conoce a quien esta donando.'
          : 'Atencion, que aqui no esta comprando nada, pero si esta dando sus datos. ' +
            (pideTelefono ? 'Le estan pidiendo el telefono, asi que le van a llamar para venderle. ' : 'Le van a escribir para venderle. ') +
            'Si solo queria mirar precios, no hace falta que rellene esto. Y si lo rellena, luego no se extrañe de las llamadas.'
      });
    }

    /* 3.ter PANTALLAS QUE PIDEN PERMISO O CAMBIAR UN AJUSTE.
     *
     * Visto en YouTube: "tu historial esta desactivado, actualizar
     * ajuste". La persona no tiene ni idea de que le estan pidiendo ni
     * de que pasa si dice que si, y el boton es grande y azul, asi que
     * lo pulsa. Lo importante no es impedirlo: es que sepa que le estan
     * pidiendo permiso para algo y que puede decir que no.
     */
    var botonAjuste = botonCon2(['actualizar ajuste', 'activar historial', 'activar', 'permitir',
      'aceptar y activar', 'si, activar']);
    if (botonAjuste) {
      var e2 = entorno(botonAjuste, 3);
      if (/historial|actividad|personaliza|recomendaci|ubicaci[oó]n|notificaci/.test(e2)) {
        lista.push({
          el: botonAjuste, gravedad: 1, corto: 'Le piden permiso',
          voz: 'Esta pantalla no le esta pidiendo dinero: le esta pidiendo permiso para guardar lo que usted hace, ' +
               'para luego enseñarle cosas a medida. No esta obligado a decir que si. ' +
               'Si no lo activa, la pagina le funciona exactamente igual, solo que le conocen menos. Usted decide.'
        });
      }
    }

    /* 3.quater BOTON DE SUSCRIBIRSE SUELTO.
     * No dentro de un formulario ni de un muro: el tipico "Suscribete"
     * o "Hazte premium" que esta por ahi en medio de la pagina. */
    var botonSus = botonCon2(['suscríbete', 'suscribete', 'hazte premium', 'hazte socio',
      'prueba premium', 'empezar prueba', 'suscribirme', 'quiero premium']);
    if (botonSus) {
      lista.push({
        el: botonSus, gravedad: 2, corto: 'Es una cuota',
        voz: 'Eso de ahi no es una compra suelta: es apuntarse a pagar todos los meses. ' +
             'Se lo cobran solos, sin volver a preguntarle, hasta que usted vaya y lo cancele. ' +
             'Y cancelarlo suele ser mas dificil que apuntarse. Si solo queria mirar, no hace falta.'
      });
    }

    /* 3.quinquies PIDEN EL TELEFONO O EL CORREO PARA "IDENTIFICARSE".
     * En Amazon y otras, la primera vez sale un recuadro rojo pidiendo
     * el telefono o el correo. El rojo asusta y parece que ha pasado
     * algo malo: hay que explicar que es normal y para que es. */
    var campoIdent = null;
    var todosCampos = [].slice.call(document.querySelectorAll('input[type=text],input[type=email],input[type=tel]'));
    for (var w = 0; w < todosCampos.length; w++) {
      var cc = todosCampos[w];
      if (!visible(cc) || cc.value.trim()) continue;
      var ctxC = (cc.name + ' ' + cc.id + ' ' + cc.placeholder + ' ' + entorno(cc, 2)).toLowerCase();
      if (/tel[eé]fono m[oó]vil|n[uú]mero de tel[eé]fono|correo electr[oó]nico|email|identif|iniciar sesi|reg[ií]strate/.test(ctxC)) {
        campoIdent = cc; break;
      }
    }
    if (campoIdent && !botonPagar) {
      lista.push({
        el: campoIdent, gravedad: 1, corto: 'Es para entrar',
        voz: 'No se asuste si lo ve en rojo, no ha hecho nada mal. Solo le estan pidiendo su telefono o su correo ' +
             'para saber quien es, como cuando le piden el nombre en una tienda. Todavia no le van a cobrar nada. ' +
             'Si no quiere darlo, puede cerrar esto y seguir mirando sin comprar.'
      });
    }

    /* 4. Aviso de cookies.
     *
     * OJO, AQUI SE METIO LA PATA UNA VEZ Y NO PUEDE VOLVER A PASAR.
     *
     * La primera version daba por hecho que el boton de "rechazar" era
     * siempre el seguro, y señalaba ese. Pero muchos periodicos (El Pais
     * entre ellos) montan un muro de "o me dejas seguirte, o te
     * suscribes": ahi rechazar te lleva DERECHO A PAGAR. O sea que la
     * app, que existe para que no les cuelen cobros, estaba empujando a
     * una persona mayor a suscribirse.
     *
     * De ahi sale la regla de oro de todo el guardaespaldas:
     * NUNCA se señala nada que pueda costar dinero. Ante la duda,
     * no se señala nada y se explica la situacion. Callarse es
     * gratis; equivocarse aqui le cuesta el dinero a otro.
     */
    var botones = [].slice.call(document.querySelectorAll('button,a,input[type=button]'));
    var rechazar = null, hayCookies = false, hayPago = false;
    for (var m = 0; m < botones.length; m++) {
      var b = botones[m];
      if (!visible(b)) continue;
      var s = limpio(b.textContent || b.value).toLowerCase();
      // "Aceptar todo" (sin la ese) lo usan Temu, YouTube y muchas mas,
      // y antes se escapaba entero: no se detectaba el aviso y la app
      // se quedaba callada justo donde mas falta hacia.
      if (/aceptar todas|aceptar todo|acepto|aceptar y continuar|permitir todas|permitir todo|de acuerdo|accept all|accept cookies|allow all|i agree|got it|ok, got it/.test(s)) hayCookies = true;
      if (/suscr[ií]b|suscripci[oó]n|pagar|abonar|hazte socio|premium|sin publicidad|desde \d|subscribe|subscription|go ad-free/.test(s)) hayPago = true;
      if (/rechazar|solo (las )?necesarias|solo esenciales|denegar|continuar sin aceptar|no aceptar|reject all|reject|decline|only necessary|necessary only|essential only|manage options/.test(s)) {
        // Y aunque ponga "rechazar": si al lado huele a dinero, no vale
        if (!/suscr|pagar|€|euro|abonar|premium/i.test(entorno(b, 2))) rechazar = b;
      }
    }

    var contextoCookies = hayCookies || /cookie|consentimiento|privacy|consent/i.test(limpio(document.body.textContent).slice(0, 3000));

    if (contextoCookies && hayPago) {
      // Muro de "consiente o paga". No se señala NADA: las dos salidas
      // son malas para la persona, y elegir por ella seria peor.
      lista.push({
        el: null, gravedad: 2, corto: 'Aquí no toque nada',
        voz: 'Cuidado con esta pagina. Le esta poniendo entre la espada y la pared: o deja que le sigan por internet, ' +
             'o le cobran una suscripcion todos los meses. No hay ninguna opcion buena, asi que no le voy a decir que pulse nada. ' +
             'Lo mas sencillo y lo que no le cuesta nada es salir de aqui y buscar la misma informacion en otro sitio.'
      });
    } else if (rechazar && contextoCookies) {
      lista.push({
        el: rechazar, gravedad: 1, corto: 'Pulse el gris',
        voz: 'Le esta preguntando si le dejan seguirle por internet para enseñarle anuncios. ' +
             'El boton grande y de color es el que dice que si. El que le señalo, el discreto, es el que dice que no. ' +
             'Puede pulsar el que le señalo tranquilamente: es gratis y la pagina funciona igual de bien.'
      });
    }

    /* RED DE SEGURIDAD FINAL.
     *
     * Ultimo filtro antes de señalar nada: si el sitio al que apunta el
     * recuadro huele a dinero, se quita el recuadro y se deja solo el
     * aviso hablado. Puede que se pierda algun caso legitimo, y es un
     * precio que merece la pena: el peor fallo posible de esta app es
     * señalarle a una persona mayor un boton que le acaba cobrando.
     */
    for (var q = 0; q < lista.length; q++) {
      var it = lista[q];
      if (!it.el) continue;
      var alrededor = (limpio(it.el.textContent) + ' ' + entorno(it.el, 2)).toLowerCase();
      var esCasilla = it.el.tagName === 'INPUT' && it.el.type === 'checkbox';
      // Las casillas marcadas SI se señalan aunque hablen de dinero:
      // ahi lo que se pide es quitar la marca, no pulsar para pagar.
      if (!esCasilla && /suscr[ií]b|suscripci[oó]n|pagar|abonar|comprar ahora|premium|hazte socio/.test(alrededor)) {
        it.el = null;
      }
    }

    lista.sort(function (a, b) { return b.gravedad - a.gravedad; });
    return lista;
  }

  /* ---------------- pintura ---------------- */
  var capa, marco, marcoPantalla, barra, corto, tranquilo, ultimo = null, quieto = 0;
  // Avisos que la persona ya ha dado por vistos en esta pagina
  var callados = {};

  function crear() {
    capa = document.createElement('div');
    capa.id = '__guardaespaldas';

    var css = document.createElement('style');
    css.textContent = '@keyframes __gPar{0%,100%{opacity:1}50%{opacity:.35}}';

    // Aqui no se usa circulo sino un RECUADRO: no se señala un boton
    // que pulsar, se rodea una cosa de la que hay que desconfiar.
    marco = document.createElement('div');
    marco.setAttribute('style',
      'position:fixed;border:5px solid #e63900;border-radius:10px;' +
      'box-shadow:0 0 0 4px #fff,0 0 26px rgba(230,57,0,.85);' +
      'z-index:2147483646;pointer-events:none;animation:__gPar 1.2s ease-in-out infinite;' +
      'transition:all .3s ease;display:none');

    // Señal discreta de que hay alguien vigilando.
    //
    // Antes, cuando no habia ningun peligro, no se veia absolutamente
    // nada. Eso esta mal por dos motivos: la persona no sabe si la estan
    // cuidando o si la app se ha colgado, y nosotros tampoco podemos
    // distinguir "todo bien" de "esto no funciona". Una banda finita y
    // tranquila lo resuelve sin molestar.
    tranquilo = document.createElement('div');
    tranquilo.setAttribute('style',
      'position:fixed;left:8px;right:8px;bottom:calc(8px + env(safe-area-inset-bottom));' +
      'background:#0b7a3b;color:#fff;border-radius:22px;' +
      'padding:6px 8px 6px 14px;z-index:2147483645;' +
      'font-family:system-ui,-apple-system,sans-serif;font-size:14px;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.35)');
    tranquilo.textContent = '\u{1F6E1} Vigilando por usted';

    /* La barra era demasiado gruesa y tapaba media pantalla. Se reduce
       la letra y el relleno: sigue viendose perfectamente, pero deja
       leer la pagina que hay detras. */
    /* UN MARCO, NO UNA BARRA.
     *
     * Van tres veces que la barra de abajo tapa la pantalla, y ya van
     * dos intentos mios de hacerla mas fina que no han bastado. El
     * problema no era el grosor: era el sitio. Cualquier cosa pegada
     * abajo se come justo la zona donde estan los botones de comprar.
     *
     * Solucion: un marco rojo fino alrededor de TODA la pantalla. Se ve
     * igual de bien -mas, porque ocupa los cuatro lados- y no tapa ni un
     * pixel de contenido. Y una pastilla pequeña, flotando, con las tres
     * palabras y los botones.
     */
    marcoPantalla = document.createElement('div');
    marcoPantalla.setAttribute('style',
      'position:fixed;inset:0;border:6px solid #b3261e;box-sizing:border-box;' +
      'pointer-events:none;z-index:2147483644;display:none;' +
      'box-shadow:inset 0 0 22px rgba(179,38,30,.35)');

    barra = document.createElement('div');
    barra.setAttribute('style',
      'position:fixed;left:8px;right:8px;bottom:calc(8px + env(safe-area-inset-bottom));' +
      'background:#b3261e;color:#fff;border-radius:24px;' +
      'padding:6px 8px 6px 16px;z-index:2147483647;' +
      'font-family:system-ui,-apple-system,sans-serif;' +
      'box-shadow:0 4px 18px rgba(0,0,0,.45);display:none;align-items:center;gap:6px');

    corto = document.createElement('div');
    corto.setAttribute('style', 'flex:1;font-size:15px;font-weight:700;line-height:1.15;min-width:0');

    var rep = document.createElement('button');
    rep.textContent = '\u{1F50A}';
    rep.setAttribute('style',
      'flex-shrink:0;width:40px;height:40px;border-radius:50%;border:2px solid #fff;' +
      'background:transparent;color:#fff;font-size:19px;padding:0');
    rep.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      if (window.__ultimaVoz) decir(window.__ultimaVoz, true);
    };

    // Casa: para poder salir de la web y volver al principio. Sin esto,
    // al entrar en una pagina uno se queda encerrado dentro.
    var casa = document.createElement('button');
    casa.textContent = '\u{1F3E0}';
    casa.setAttribute('style',
      'flex-shrink:0;width:40px;height:40px;border-radius:50%;border:2px solid #fff;' +
      'background:transparent;color:#fff;font-size:19px;padding:0');
    casa.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      try { if (window.Android && window.Android.inicio) window.Android.inicio(); } catch (e) {}
    };

    // La misma casa, tambien en la banda verde de "todo tranquilo"
    tranquilo.style.display = 'flex';
    tranquilo.style.alignItems = 'center';
    tranquilo.style.gap = '12px';
    var etiqueta = document.createElement('div');
    etiqueta.setAttribute('style', 'flex:1;text-align:left');
    etiqueta.innerHTML = '\u{1F6E1} Vigilando por usted ' +
      '<span id="__gEstadoIA" style="font-size:13px;color:#ffffffaa"></span>';
    var casa2 = casa.cloneNode(true);
    casa2.setAttribute('style',
      'flex-shrink:0;width:44px;height:44px;border-radius:50%;border:3px solid #fff;' +
      'background:transparent;color:#fff;font-size:20px');
    casa2.onclick = casa.onclick;
    tranquilo.textContent = '';
    tranquilo.appendChild(etiqueta);
    tranquilo.appendChild(casa2);

    /* CERRAR EL AVISO.
       Antes el aviso se quedaba puesto para siempre y repitiendose: si
       la persona ya lo ha entendido y decide seguir, la app le estaba
       dando la lata sin parar. Ahora se puede decir "ya lo he visto" y
       ese aviso concreto no vuelve a salir en esta pagina. */
    var visto = document.createElement('button');
    visto.textContent = '✓';
    visto.setAttribute('style',
      'flex-shrink:0;width:40px;height:40px;border-radius:50%;border:2px solid #fff;' +
      'background:#ffffff22;color:#fff;font-size:19px;font-weight:800;padding:0');
    visto.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      if (ultimo) callados[ultimo] = true;
      ultimo = null;
      latido();
    };

    var botones2 = [corto, rep, visto, casa];
    for (var z = 0; z < botones2.length; z++) barra.appendChild(botones2[z]);
    capa.appendChild(css); capa.appendChild(marco); capa.appendChild(marcoPantalla);
    capa.appendChild(tranquilo); capa.appendChild(barra);
    document.documentElement.appendChild(capa);
  }

  /* La barra de abajo tapaba el final de la pagina y no habia forma de
     leer lo que ponia ahi. Se le mete a la propia pagina un hueco al
     final igual de alto que la barra, asi nada queda escondido. */
  /* Encoge la barra a una tira fina. El aviso ya se ha dicho y ya se ha
     leido; a partir de ahi solo tiene que quedar el recordatorio, sin
     comerse la pantalla. Se puede volver a oir con el altavoz. */
  function encoger() {
    if (!barra || barra.style.display === 'none') return;
    barra.style.padding = '6px 12px calc(6px + env(safe-area-inset-bottom))';
    corto.style.fontSize = '15px';
    apartarContenido();
  }

  function apartarContenido() {
    var alto = 0;
    if (barra && barra.style.display !== 'none') alto = barra.offsetHeight;
    else if (tranquilo && tranquilo.style.display !== 'none') alto = tranquilo.offsetHeight;
    // Ya no se aparta nada: el aviso es un marco por los bordes y una
    // pastilla flotante, asi que no tapa contenido. Se deja un hueco
    // minimo para que la pastilla no se coma el ultimo boton.
    if (document.body) document.body.style.paddingBottom = '64px';
  }

  function rodear(el) {
    /* NO se mueve la pagina.
     *
     * Antes esto hacia scrollIntoView cada vez que se recolocaba, y en
     * paginas que cambian solas (YouTube) se quedaba subiendo y bajando
     * sin parar: mareaba y no se podia ni leer. Aqui solo vigilamos, no
     * hay ningun paso que dar, asi que si el elemento no se ve, no se
     * rodea y punto. Mover la pantalla debajo de una persona mayor la
     * desorienta mas que ayudarla. */
    var r = el.getBoundingClientRect();
    var altoBarra = (barra.style.display !== 'none') ? barra.offsetHeight : tranquilo.offsetHeight;
    if (r.bottom < 40 || r.top > window.innerHeight - altoBarra - 10) {
      marco.style.display = 'none';
      return;
    }
    marco.style.left = (r.left - 7) + 'px';
    marco.style.top = (r.top - 7) + 'px';
    marco.style.width = (r.width + 14) + 'px';
    marco.style.height = (r.height + 14) + 'px';
    marco.style.display = 'block';
  }

  function decir(f, forzar) {
    try { if (window.Android && window.Android.decir) { window.Android.decir(f, !!forzar); return; } } catch (e) {}
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(f);
      u.lang = 'es-ES'; u.rate = 0.86;
      speechSynthesis.speak(u);
    }
  }

  /* Mete lo que ha dicho la IA en la misma lista que las reglas, para
     que compitan por gravedad como uno mas. La IA no manda sobre las
     reglas ni al reves: gana el aviso mas grave.

     Y la regla de oro se aplica IGUAL a la IA: si dice que señalemos
     algo que huele a dinero, se avisa pero no se señala. No me fio ni
     de ella para eso. */
  function conIA(lista) {
    if (!avisoIA || !avisoIA.hay_aviso) return lista;
    var el = null;
    if (avisoIA.senalar) {
      var todos = [].slice.call(document.querySelectorAll('button,a,input[type=submit],input[type=button]'));
      for (var i = 0; i < todos.length; i++) {
        if (visible(todos[i]) && textoDe(todos[i]) === avisoIA.senalar) { el = todos[i]; break; }
      }
      if (el && /suscr[ií]b|pagar|abonar|premium|comprar/i.test(textoDe(el) + ' ' + entorno(el, 2))) {
        el = null;
      }
    }
    return lista.concat([{
      el: el,
      gravedad: avisoIA.gravedad || 1,
      corto: avisoIA.corto || 'Atención',
      voz: avisoIA.voz
    }]);
  }

  function latido() {
    var t = conIA(trampas()).filter(function (x) { return !callados[x.corto]; });
    t.sort(function (a, b) { return b.gravedad - a.gravedad; });
    if (!t.length) {
      // Todo tranquilo: se quita el recuadro y el aviso, pero se deja la
      // banda verde. Callarse del todo hacia imposible saber si estaba
      // vigilando o si la app se habia caido.
      marco.style.display = 'none';
      marcoPantalla.style.display = 'none';
      barra.style.display = 'none';
      tranquilo.style.display = 'flex';
      ultimo = null;
      return;
    }
    var p = t[0];
    tranquilo.style.display = 'none';
    barra.style.display = 'flex';
    marcoPantalla.style.display = 'block';
    // Puede no haber nada que señalar, y esta bien: hay avisos que solo
    // se dicen ("aqui no toque nada"). Antes esto habria reventado.
    if (p.el) rodear(p.el); else marco.style.display = 'none';
    if (ultimo !== p.corto) {
      ultimo = p.corto;
      corto.textContent = p.corto;
      window.__ultimaVoz = p.voz;
      decir(p.voz, false);
    }
  }

  /* ===================================================================
     LA IA
     ===================================================================
     Hasta aqui todo lo de arriba son reglas que escribi a mano: solo
     reconocen lo que se me ocurrio prever. Por eso fallaban en paginas
     que no habia visto -las de adultos, las fraudulentas, las que se
     inventan mañana-.

     Esto le enseña la pantalla a una IA y le pregunta que le estan
     pidiendo a la persona. Funciona en cualquier pagina, este escrita
     como este.

     Con dos condiciones que no se negocian:
       - Las reglas mandan primero. Contestan al instante; la IA llega
         despues a afinar. Nadie se queda mirando una pantalla parada.
       - NUNCA se manda lo que la persona escribe. Solo las etiquetas,
         los botones y si una casilla esta marcada. Su DNI, su telefono
         y su tarjeta no salen de su movil.
     =================================================================== */
  var SERVIDOR = 'https://ai-council-ekax.onrender.com/guardian/mirar';
  var avisoIA = null;          // lo ultimo que dijo la IA
  var huellaPreguntada = '';   // para no repetir la misma pantalla
  var preguntando = false;

  function textoDe(e) { return limpio(e.textContent || e.value || ''); }

  /* Estado de la IA, visible en la banda verde.
   *
   * Esto no es un adorno: sin verlo, "la IA no dice nada" puede ser que
   * este funcionando y no vea peligro, que no llegue al servidor, o que
   * el servidor la rechace. Tres cosas muy distintas que se arreglan de
   * forma muy distinta. Se pone en pequeño y se quitara cuando esto
   * este rodado. */
  var ultimoEstadoIA = '';
  function estadoIA(e) {
    ultimoEstadoIA = e;
    var el = document.getElementById('__gEstadoIA');
    if (!el) return;
    var mapa = { pensando: '· mirando…', ok: '· todo bien', aviso: '· ojo' };
    el.textContent = mapa[e] || ('· ' + e);
    el.style.color = e.indexOf('fallo') === 0 ? '#ffd0d0' : '#ffffffaa';
  }

  /* Recoge la ESTRUCTURA de la pantalla. Lo importante de esta funcion
     es lo que NO recoge: en ningun sitio se lee el .value de un campo
     de texto. Solo si esta vacio o no. */
  function retrato() {
    var botones = [];
    [].slice.call(document.querySelectorAll('button,a,input[type=submit],input[type=button]'))
      .forEach(function (b) {
        if (!visible(b)) return;
        var t = textoDe(b);
        if (t.length > 1 && t.length < 60 && botones.indexOf(t) === -1) botones.push(t);
      });

    var campos = [];
    [].slice.call(document.querySelectorAll('input,select,textarea')).forEach(function (c) {
      if (!visible(c) || c.type === 'hidden') return;
      var et = c.getAttribute('aria-label') || c.placeholder || '';
      if (!et && c.id) {
        var l = document.querySelector('label[for="' + c.id + '"]');
        if (l) et = limpio(l.textContent);
      }
      if (!et) et = limpio(entorno(c, 1)).slice(0, 90);
      if (!et) et = c.name || c.type;
      campos.push({
        etiqueta: String(et).slice(0, 160),
        tipo: (c.type || c.tagName).toLowerCase().slice(0, 20),
        marcada: c.type === 'checkbox' ? !!c.checked : null,
        vacia: (c.value || '').trim().length === 0     // SIN decir que hay
      });
    });

    var encabezados = [], textos = [], importes = [];
    [].slice.call(document.querySelectorAll('h1,h2,h3')).forEach(function (h) {
      if (visible(h) && encabezados.length < 12) {
        var t = textoDe(h); if (t) encabezados.push(t.slice(0, 120));
      }
    });
    [].slice.call(document.querySelectorAll('p,li,label,span,div')).forEach(function (z) {
      if (z.children.length || !visible(z)) return;
      var t = textoDe(z);
      if (t.length > 25 && t.length < 220 && textos.length < 25) textos.push(t);
      var pr = t.match(/\d+[.,]\d{2}\s*€|€\s*\d+[.,]\d{2}/);
      if (pr && importes.length < 10 && importes.indexOf(pr[0]) === -1) importes.push(pr[0]);
    });

    return {
      dominio: location.hostname,          // el dominio, NUNCA la url entera:
                                           // las urls llevan identificadores
                                           // y a veces datos dentro
      titulo: (document.title || '').slice(0, 200),
      encabezados: encabezados,
      botones: botones.slice(0, 40),
      campos: campos.slice(0, 25),
      textos: textos,
      importes: importes
    };
  }

  function huellaDe(r) {
    return r.dominio + '|' + r.botones.slice(0, 12).join(',') + '|' +
           r.campos.map(function (c) { return c.etiqueta + c.marcada; }).slice(0, 8).join(',');
  }

  function preguntarIA() {
    if (preguntando) return;
    var r = retrato();
    // Sin botones ni campos no hay nada que valorar: no se gasta llamada
    if (!r.botones.length && !r.campos.length) return;
    var h = huellaDe(r);
    if (h === huellaPreguntada) return;
    huellaPreguntada = h;
    preguntando = true;

    estadoIA('pensando');
    fetch(SERVIDOR, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Movil': window.__idMovil || 'app' },
      body: JSON.stringify(r)
    })
      .then(function (res) {
        if (!res.ok) throw new Error('error ' + res.status);
        return res.json();
      })
      .then(function (a) {
        preguntando = false;
        if (a && a.hay_aviso) { avisoIA = a; estadoIA('aviso'); latido(); }
        else { avisoIA = null; estadoIA('ok'); }
      })
      .catch(function (e) {
        // Sin internet o servidor caido: las reglas siguen solas.
        preguntando = false;
        estadoIA('fallo:' + (e && e.message ? e.message : '?'));
      });
  }

  crear();
  setTimeout(latido, 900);
  setInterval(latido, 900);          // mas seguido: los avisos de cookies
                                     // se mueven y aparecen tarde
  setTimeout(preguntarIA, 1800);     // la IA llega despues, sin frenar nada
  setInterval(preguntarIA, 4000);

  function recolocar() {
    apartarContenido();
    var t = trampas();
    if (t.length && t[0].el) rodear(t[0].el);
  }
  window.addEventListener('scroll', recolocar, true);
  window.addEventListener('resize', recolocar);

  /* Los avisos de cookies aparecen despues de que la pagina cargue, y
     muchos se mueven o cambian de sitio segun se va usando. Antes el
     recuadro se quedaba clavado donde estaba al principio. Vigilando los
     cambios de la pagina se recoloca solo en cuanto algo se mueve. */
  try {
    var vigia = new MutationObserver(function () {
      clearTimeout(window.__gRe);
      window.__gRe = setTimeout(recolocar, 250);
    });
    vigia.observe(document.documentElement, { childList: true, subtree: true, attributes: true,
                                              attributeFilter: ['style', 'class'] });
  } catch (e) {}
})();
