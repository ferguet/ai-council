/* =====================================================================
   GUIA HABLADA - CITA PREVIA DEL DNI
   =====================================================================
   Se inyecta en la web real de citapreviadnie.es (Policia Nacional).

   Por que este tramite y no el certificado digital: el certificado
   obliga a instalar un programa de escritorio, asi que en un movil no
   se puede terminar. Se comprobo en la web real antes de escribir nada.
   Este si se puede hacer entero desde el telefono.

   COMO ESTA PENSADO, tras ver como se maneja de verdad una persona
   mayor:
     - NO leen. En pantalla van tres o cuatro palabras; lo demas, voz.
     - Se les olvida entre pantalla y pantalla: se repite solo si se
       quedan parados.
     - Lo que les hunde no es no ver el boton, es no saber QUE les
       piden. Por eso cada paso explica el campo, no solo lo señala.

   LO QUE ESTA GUIA NO HACE, A PROPOSITO:
     - No escribe nada por la persona. Ni un digito.
     - No guarda datos ni los manda a ningun sitio.
     - No resuelve el captcha: eso lo hace la persona. Solo le dice
       que es y le enseña el boton de escucharlo si no lo ve bien.
   ===================================================================== */
(function () {
  if (window.__guiaViva) return;
  window.__guiaViva = true;

  /* ---------------- utilidades ---------------- */
  function visible(e) {
    if (!e || !e.offsetParent) return false;
    var r = e.getBoundingClientRect();
    return r.width > 8 && r.height > 8;
  }
  function txt(e) { return (e.textContent || e.value || '').replace(/\s+/g, ' ').trim().toLowerCase(); }

  function botonCon(palabras) {
    var t = [].slice.call(document.querySelectorAll('a,button,input[type=submit],input[type=button]'));
    for (var i = 0; i < t.length; i++) {
      if (!visible(t[i])) continue;
      var s = txt(t[i]);
      for (var j = 0; j < palabras.length; j++) if (s.indexOf(palabras[j]) !== -1) return t[i];
    }
    return null;
  }
  // Los campos de esta web tienen nombres claros (numDocumento, codEquipo...),
  // asi que se busca por ahi: es mucho mas fiable que adivinar por el texto.
  function campo(nombre) {
    var c = document.querySelector('[name="' + nombre + '"], #' + nombre);
    return (c && visible(c) && c.value.trim().length === 0) ? c : null;
  }
  function campoSea(nombre) {
    var c = document.querySelector('[name="' + nombre + '"], #' + nombre);
    return (c && visible(c)) ? c : null;
  }

  /* ---------------------------------------------------------------
     EL GUION. Cada paso se reconoce solo mirando la pantalla, no hay
     contador: si la persona vuelve atras o recarga, la guia se
     recoloca sola sin perderse.
     --------------------------------------------------------------- */
  var GUION = [

    { id: 'continuar',
      buscar: function () { return botonCon(['continuar']); },
      corto: 'Toque aquí',
      voz: 'Vamos a pedirle la cita para el de eneí. Toque donde está el círculo naranja, en Continuar.' },

    { id: 'acceso',
      buscar: function () { return botonCon(['acceso con datos dni']); },
      corto: 'Este de aquí',
      voz: 'Le dan a elegir dos formas. Usted la primera, la de acceso con datos. La otra necesita un aparato lector de tarjetas que usted no tiene.' },

    { id: 'numero',
      buscar: function () { return campo('numDocumento'); },
      corto: 'Los números',
      voz: 'Escriba aquí los ocho números de su de eneí, pero sin la letra del final. Solo los números. La letra va aparte, en la casilla siguiente.' },

    { id: 'letra',
      buscar: function () { return campo('letraDocumento'); },
      corto: 'Ahora la letra',
      voz: 'Ahora sí, la letra del final de su de eneí. Ella sola, en esta casilla pequeña.' },

    { id: 'equipo',
      buscar: function () { return campo('codEquipo'); },
      corto: 'Mire el reverso',
      voz: 'Ahora le piden el equipo de expedición. Suena raro, pero es fácil: dele la vuelta a su de eneí. En el reverso, pegado al lado izquierdo, debajo de donde pone EQUIPO, hay un código de nueve letras y números. Cópielo aquí tal cual.' },

    { id: 'validez',
      buscar: function () { return campo('fechaValidez'); },
      corto: 'La caducidad',
      voz: 'La fecha de caducidad de su de eneí, con dia, mes y año. Y atención a esto: si su de eneí no caduca, si pone PERMANENTE, entonces escriba usted la palabra PERMANENTE, con letras. Es lo que les pasa a los mayores de setenta años.' },

    { id: 'captcha',
      buscar: function () { return campo('codSeguridad'); },
      corto: 'Copie las letras',
      voz: 'Ya lo último. Ahí al lado salen unas letras torcidas: cópielas tal cual en esta casilla. Sirven para comprobar que es una persona y no una máquina. Si no las ve bien, suele haber un botón para escucharlas.' },

    { id: 'enviar',
      buscar: function () { return botonCon(['aceptar', 'enviar', 'continuar']); },
      corto: 'Ya está: envíe',
      voz: 'Ya está todo relleno. Pulse este botón para enviarlo.' }
  ];

  /* ---------------------------------------------------------------
     PROBLEMAS: lo que pasa cuando algo sale mal.

     Esto es tan importante como guiar. Cuando la pantalla les suelta un
     error, la persona da por hecho que la ha liado ella, lo repite una y
     otra vez, y acaba rindiendose convencida de que no sabe usar esto.
     Muchas veces NO ES CULPA SUYA -no hay citas, se caduco la sesion-,
     y nadie se lo dice nunca.

     Cuando se detecta uno de estos casos, se avisa ANTES que cualquier
     otro paso, se quita el circulo (no hay nada que pulsar) y se le
     explica en voz alta que ha pasado y que puede hacer.
     --------------------------------------------------------------- */
  var PROBLEMAS = [
    { patron: /no hay citas|sin citas disponibles|no existen citas|no se han encontrado citas|no hay huecos/i,
      corto: 'No es culpa suya',
      voz: 'Escuche bien esto: no ha hecho usted nada mal. Lo que pasa es que ahora mismo no quedan citas libres. Le pasa a todo el mundo. Suelen soltar citas nuevas por la mañana temprano, asi que lo mejor es volver a intentarlo mañana sobre las ocho. No hace falta que repita nada ahora.' },

    { patron: /c[oó]digo de seguridad.{0,40}(no|incorrect|err)|caracteres.{0,30}no coinciden/i,
      corto: 'Las letras, otra vez',
      voz: 'Solo han fallado las letras torcidas del final. No se preocupe, es muy facil equivocarse porque se leen fatal. Le han puesto unas nuevas: copielas otra vez. Si no las ve bien, busque el botoncito para escucharlas.' },

    { patron: /datos.{0,30}(no son correctos|incorrectos|err[oó]neos)|no coinciden los datos|no consta/i,
      corto: 'Revise el DNI',
      voz: 'Dice que los datos no le cuadran. Casi siempre es una de estas tres cosas: que la letra del de eneí se haya escrito junto a los números en vez de en su casilla, que el código del reverso tenga alguna letra cambiada, o la fecha de caducidad. Miremos el de eneí otra vez con calma, sin prisa.' },

    { patron: /sesi[oó]n.{0,30}(caducad|expirad|finalizad)|tiempo de espera agotado/i,
      corto: 'Empezamos de nuevo',
      voz: 'Se ha agotado el tiempo que dan para rellenarlo. No es culpa suya: dan muy poco rato. Volvemos a empezar y esta vez lo hacemos del tirón. Tenga el de eneí a mano antes de empezar.' }
  ];

  function buscarProblema() {
    // solo se mira lo que se VE en pantalla: asi no se confunde con
    // textos de ayuda o avisos legales escondidos en el codigo
    var zonas = [].slice.call(document.querySelectorAll('div,p,span,td,li,h1,h2,h3,strong,label'));
    for (var i = 0; i < zonas.length; i++) {
      var z = zonas[i];
      if (z.children.length > 0 || !visible(z)) continue;
      var t = (z.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 8 || t.length > 300) continue;
      for (var j = 0; j < PROBLEMAS.length; j++) {
        if (PROBLEMAS[j].patron.test(t)) return PROBLEMAS[j];
      }
    }
    return null;
  }

  /* Campos que hay que DEJAR VACIOS. No se señalan (haria pensar que
     falta rellenarlos), pero si la persona los toca se le explica.
     Sin esto, se quedan atascados intentando rellenar algo que no les
     corresponde -y dejar un hueco en blanco les da mucha inseguridad. */
  var DEJAR_VACIOS = [
    { nombre: 'numSoporte',
      voz: 'Esa casilla déjela vacía. El número de soporte es solo para quien usa el de eneí electrónico con un lector. Usted no tiene que poner nada ahí. No pasa nada por dejarla en blanco.' }
  ];

  /* ---------------- pintura ---------------- */
  var capa, circulo, mano, barra, corto;

  function crear() {
    capa = document.createElement('div');
    capa.id = '__guia_mayores';

    var css = document.createElement('style');
    css.textContent = '@keyframes __gLat{0%,100%{transform:scale(1);opacity:1}' +
                      '50%{transform:scale(1.32);opacity:.45}}';

    circulo = document.createElement('div');
    circulo.setAttribute('style',
      'position:fixed;width:66px;height:66px;margin:-33px 0 0 -33px;border-radius:50%;' +
      'border:7px solid #e63900;box-shadow:0 0 0 5px #fff,0 0 30px rgba(230,57,0,.95);' +
      'z-index:2147483646;pointer-events:none;animation:__gLat 1.25s ease-in-out infinite;' +
      'transition:top .3s ease,left .3s ease;display:none');

    mano = document.createElement('div');
    mano.textContent = '\u{1F446}';
    mano.setAttribute('style',
      'position:fixed;font-size:36px;z-index:2147483646;pointer-events:none;' +
      'transition:top .3s ease,left .3s ease;display:none;' +
      'filter:drop-shadow(0 2px 4px rgba(0,0,0,.5))');

    barra = document.createElement('div');
    barra.setAttribute('style',
      'position:fixed;left:0;right:0;bottom:0;background:#0b7a3b;color:#fff;' +
      'padding:20px 18px calc(20px + env(safe-area-inset-bottom));z-index:2147483647;' +
      'font-family:system-ui,-apple-system,sans-serif;' +
      'box-shadow:0 -8px 30px rgba(0,0,0,.45);display:flex;align-items:center;gap:14px');

    corto = document.createElement('div');
    corto.setAttribute('style', 'flex:1;font-size:29px;font-weight:800;line-height:1.2');

    var rep = document.createElement('button');
    rep.textContent = '\u{1F50A}';
    rep.setAttribute('style',
      'flex-shrink:0;width:64px;height:64px;border-radius:50%;border:4px solid #fff;' +
      'background:transparent;color:#fff;font-size:27px');

    // Toque normal: repetir lo ultimo.
    // TRES toques seguidos: modo prueba, va soltando los avisos de
    // problema uno tras otro. Sirve para oirlos todos sin tener que
    // esperar a que ocurran de verdad (las citas agotadas o la sesion
    // caducada no se pueden provocar cuando uno quiere). Va escondido
    // a proposito: la persona mayor no lo va a encontrar por accidente.
    var toques = 0, reloj = null, cual = 0;
    rep.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      toques++;
      clearTimeout(reloj);
      reloj = setTimeout(function () {
        if (toques >= 3) {
          var p = PROBLEMAS[cual % PROBLEMAS.length];
          cual++;
          corto.textContent = '[prueba] ' + p.corto;
          window.__ultimaVoz = p.voz;
          decir(p.voz, true);
        } else if (window.__ultimaVoz) {
          decir(window.__ultimaVoz, true);
        }
        toques = 0;
      }, 450);
    };

    // Casa: para poder dejarlo y volver al principio en cualquier
    // momento. Sin esto uno se queda encerrado dentro de la web.
    var casa = document.createElement('button');
    casa.textContent = '\u{1F3E0}';
    casa.setAttribute('style',
      'flex-shrink:0;width:64px;height:64px;border-radius:50%;border:4px solid #fff;' +
      'background:transparent;color:#fff;font-size:27px');
    casa.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      try { if (window.Android && window.Android.inicio) window.Android.inicio(); } catch (e) {}
    };

    barra.appendChild(corto); barra.appendChild(rep); barra.appendChild(casa);
    capa.appendChild(css); capa.appendChild(circulo);
    capa.appendChild(mano); capa.appendChild(barra);
    document.documentElement.appendChild(capa);
  }

  function colocar(el) {
    var r = el.getBoundingClientRect();
    // si queda tapado por la barra verde o fuera de vista, se sube solo:
    // la persona no tiene que buscar nada ni hacer scroll
    if (r.top < 70 || r.bottom > window.innerHeight - 160) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      r = el.getBoundingClientRect();
    }
    var x = r.left + Math.min(36, r.width / 2), y = r.top + r.height / 2;
    circulo.style.left = x + 'px'; circulo.style.top = y + 'px';
    mano.style.left = (x + 14) + 'px'; mano.style.top = (y + 22) + 'px';
    circulo.style.display = 'block'; mano.style.display = 'block';
  }
  function esconder() {
    circulo.style.display = 'none'; mano.style.display = 'none';
  }

  function decir(frase, forzar) {
    try {
      if (window.Android && window.Android.decir) { window.Android.decir(frase, !!forzar); return; }
    } catch (e) {}
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(frase);
      u.lang = 'es-ES'; u.rate = 0.86;
      speechSynthesis.speak(u);
    }
  }

  /* Avisar cuando tocan un campo que deben dejar vacio */
  var yaAvisado = {};
  DEJAR_VACIOS.forEach(function (d) {
    var c = campoSea(d.nombre);
    if (!c) return;
    c.addEventListener('focus', function () {
      if (yaAvisado[d.nombre]) return;
      yaAvisado[d.nombre] = true;
      decir(d.voz, true);
      corto.textContent = 'Déjelo vacío';
    });
  });

  /* ---------------- el latido ---------------- */
  var actual = null, quieto = 0;

  function latido() {
    // PRIMERO los problemas. Si la pantalla trae un error, no tiene
    // ningun sentido seguir señalando casillas: hay que explicarle que
    // ha pasado y, sobre todo, que no es culpa suya.
    var pega = buscarProblema();
    if (pega) {
      esconder();                       // no hay nada que pulsar
      barra.style.background = '#0a5fa8';
      if (actual !== 'problema:' + pega.corto) {
        actual = 'problema:' + pega.corto;
        quieto = 0;
        corto.textContent = pega.corto;
        window.__ultimaVoz = pega.voz;
        decir(pega.voz, false);
      }
      return;
    }
    barra.style.background = '#0b7a3b';

    var paso = null, el = null;
    for (var i = 0; i < GUION.length; i++) {
      var e = GUION[i].buscar();
      if (e && visible(e)) { paso = GUION[i]; el = e; break; }
    }
    if (!paso) {
      esconder();
      if (actual !== 'nada') { actual = 'nada'; corto.textContent = 'Un momento…'; }
      return;
    }
    colocar(el);

    if (actual !== paso.id) {
      actual = paso.id; quieto = 0;
      corto.textContent = paso.corto;
      window.__ultimaVoz = paso.voz;
      decir(paso.voz, false);
    } else {
      quieto++;
      if (quieto === 14) { decir(paso.voz, true); quieto = 0; }   // ~20 s parado
    }
  }

  crear();
  latido();
  setInterval(latido, 1400);
  window.addEventListener('scroll', function () {
    for (var i = 0; i < GUION.length; i++) {
      var e = GUION[i].buscar();
      if (e && visible(e)) { colocar(e); break; }
    }
  }, true);
})();
