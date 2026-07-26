/* =====================================================================
   GUIA HABLADA - BAJA TEMPORAL DE UN VEHICULO (DGT)
   =====================================================================
   Se inyecta en las paginas de sede.dgt.gob.es cuando la persona viene
   de pedir "dar de baja el coche".

   DIFERENCIA IMPORTANTE CON LA GUIA DEL DNI: aquella se comprobo entera
   navegando la web real, campo por campo. Esta NO: el tramite de verdad
   esta detras de un login con Cl@ve/certificado/DNI electronico, y sin
   esas credenciales no se puede llegar a ver el formulario para copiar
   los nombres exactos de los campos. Por eso aqui no se buscan campos
   por su nombre (como "numDocumento" en la del DNI): se reconoce la
   FORMA de cada paso (una matricula, un boton de continuar, un aviso de
   pago), igual que hace el modo guardaespaldas con las tiendas. Es mas
   prudente equivocarse por defecto hacia "no digo nada" que hacia
   "señalo el boton que no es".

   Lo que esta guia SI sabe seguro, porque esta en la propia informacion
   publica de la DGT (no dentro del formulario):
     - Hace falta Cl@ve, certificado digital o DNI electronico. No hay
       forma de evitarlo.
     - Al final se paga una tasa oficial de 8,67 euros. Es obligatoria
       y legitima: no es ningun timo, aunque se le parezca por pedir la
       tarjeta.

   LO QUE ESTA GUIA NO HACE, A PROPOSITO:
     - No elige la matricula por la persona si hay mas de una: eso lo
       decide ella, nunca la app.
     - No escribe ni un digito ni guarda ni manda nada a ningun lado.
   ===================================================================== */
(function () {
  if (window.__guiaViva) return;
  window.__guiaViva = true;

  function visible(e) {
    if (!e || !e.offsetParent) return false;
    var r = e.getBoundingClientRect();
    return r.width > 8 && r.height > 8;
  }
  function limpio(t) { return (t || '').replace(/\s+/g, ' ').trim(); }
  function txt(e) { return limpio(e.textContent || e.value || '').toLowerCase(); }

  function botonCon(palabras) {
    var t = [].slice.call(document.querySelectorAll('a,button,input[type=submit],input[type=button]'));
    for (var i = 0; i < t.length; i++) {
      if (!visible(t[i])) continue;
      var s = txt(t[i]);
      if (s.length > 60) continue;
      for (var j = 0; j < palabras.length; j++) if (s.indexOf(palabras[j]) !== -1) return t[i];
    }
    return null;
  }

  // Texto visible de toda la pagina, para detectar en que pantalla estamos
  // sin depender de nombres de campo que no hemos podido comprobar.
  function textoPagina() {
    return limpio(document.body ? document.body.textContent : '').toLowerCase();
  }

  var MATRICULA = /\b\d{4}[\s-]?[a-z]{3}\b/i;

  /* ---------------------------------------------------------------
     EL GUION. Cada paso se reconoce por como se ve la pantalla, no por
     un numero de paso: si la persona vuelve atras, la guia se recoloca
     sola.
     --------------------------------------------------------------- */
  var GUION = [

    { id: 'identificarse',
      buscar: function () {
        // Solo tiene sentido este aviso si TODAVIA no hay una matricula
        // en pantalla (o sea, si aun no hemos entrado).
        if (MATRICULA.test(textoPagina())) return null;
        return botonCon(['cl@ve pin', 'cl@ve']) || botonCon(['certificado electr', 'dni electr']);
      },
      corto: 'Identifíquese',
      voz: 'Para este trámite hace falta entrar con Cl@ve, con certificado digital o con el DNI electrónico. Si tiene el Cl@ve PIN es lo más sencillo: toque esa opción y siga las instrucciones que le den. Si no tiene ninguna de las tres cosas, dígame "necesito el Cl@ve PIN" y le ayudo a sacárselo, o vaya en persona a la Jefatura de Tráfico pidiendo cita antes.' },

    { id: 'matricula_una',
      buscar: function () {
        var candidatos = [].slice.call(document.querySelectorAll('a,button,tr,li'));
        var encontrados = [];
        for (var i = 0; i < candidatos.length; i++) {
          var c = candidatos[i];
          if (!visible(c)) continue;
          var t = limpio(c.textContent);
          if (t.length > 0 && t.length < 90 && MATRICULA.test(t)) encontrados.push(c);
        }
        // Solo se señala si hay EXACTAMENTE una: con varias, elegir la
        // suya es una decision de la persona, no de la app.
        return encontrados.length === 1 ? encontrados[0] : null;
      },
      corto: 'Su matrícula',
      voz: 'Ahí está la matrícula de su coche. Tóquela para elegirla.' },

    { id: 'matricula_varias',
      buscar: function () {
        var candidatos = [].slice.call(document.querySelectorAll('a,button,tr,li'));
        var n = 0;
        for (var i = 0; i < candidatos.length; i++) {
          if (visible(candidatos[i]) && MATRICULA.test(limpio(candidatos[i].textContent))) n++;
        }
        return n > 1 ? true : null;   // no hay elemento que señalar, solo avisar
      },
      corto: 'Elija su coche',
      esAviso: true,
      voz: 'Le salen varias matrículas. Busque la de su coche y tóquela usted mismo: yo no puedo elegir por usted cuál es.' },

    { id: 'pagar',
      buscar: function () {
        var t = textoPagina();
        if (!/\bpagar\b/.test(t)) return null;
        if (!/8,67|8.67|€|tasa/.test(t)) return null;
        return botonCon(['pagar']);
      },
      corto: 'Pago oficial',
      voz: 'Ya está casi. Ahora toca pagar la tasa de ocho euros con sesenta y siete céntimos. Es una tasa oficial de Tráfico, obligatoria para este trámite: no es ningún cobro raro, aunque le pidan la tarjeta igual que en una tienda. Puede pagar tranquilo.' },

    { id: 'continuar',
      buscar: function () { return botonCon(['continuar', 'siguiente', 'confirmar', 'realizar la baja']); },
      corto: 'Toque aquí',
      voz: 'Toque este botón para seguir con el trámite.' }
  ];

  /* ---------------------------------------------------------------
     PROBLEMAS conocidos por la informacion publica de la DGT. No se han
     podido ver los mensajes de error exactos (estan detras del login),
     asi que estos patrones son mas generales que los de la guia del DNI
     y conviene revisarlos con casos reales.
     --------------------------------------------------------------- */
  var PROBLEMAS = [
    { patron: /no dispone de.{0,20}certificado|certificado no v[aá]lido|no se ha podido verificar su identidad/i,
      corto: 'No ha podido entrar',
      voz: 'Parece que no ha podido identificarse. No es culpa suya: a veces el Cl@ve PIN caduca a los pocos minutos si no se usa. Puede volver a pedirlo, o si lo prefiere, vaya en persona a la Jefatura de Tráfico con cita previa.' },

    { patron: /notificaci[oó]n de venta pendiente|trabas? administrativ|precintad|no se puede (dar de baja|tramitar)/i,
      corto: 'Este coche no se puede',
      voz: 'La página dice que este vehículo tiene algo pendiente que impide la baja ahora mismo. No lo intente varias veces: lo mejor es llamar al teléfono de Tráfico, el cero sesenta, y preguntar qué es exactamente lo que falta.' },

    { patron: /sesi[oó]n.{0,30}(caducad|expirad|finalizad)|tiempo de espera agotado/i,
      corto: 'Empezamos de nuevo',
      voz: 'Se ha agotado el tiempo. No es culpa suya, dan poco rato. Vuelva a entrar y tenga a mano la Cl@ve o el certificado antes de empezar, para no perder tiempo buscándolo a mitad.' }
  ];

  function buscarProblema() {
    var zonas = [].slice.call(document.querySelectorAll('div,p,span,td,li,h1,h2,h3,strong,label'));
    for (var i = 0; i < zonas.length; i++) {
      var z = zonas[i];
      if (z.children.length > 0 || !visible(z)) continue;
      var t = limpio(z.textContent);
      if (t.length < 8 || t.length > 300) continue;
      for (var j = 0; j < PROBLEMAS.length; j++) {
        if (PROBLEMAS[j].patron.test(t)) return PROBLEMAS[j];
      }
    }
    return null;
  }

  /* ---------------- pintura (igual que la guia del DNI) ---------------- */
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
    corto.setAttribute('style', 'flex:1;font-size:26px;font-weight:800;line-height:1.2');

    var rep = document.createElement('button');
    rep.textContent = '\u{1F50A}';
    rep.setAttribute('style',
      'flex-shrink:0;width:64px;height:64px;border-radius:50%;border:4px solid #fff;' +
      'background:transparent;color:#fff;font-size:27px');
    rep.onclick = function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      if (window.__ultimaVoz) decir(window.__ultimaVoz, true);
    };

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

  /* ---------------- el latido ---------------- */
  var actual = null, quieto = 0;

  function latido() {
    var pega = buscarProblema();
    if (pega) {
      esconder();
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
      if (e) { paso = GUION[i]; el = (e === true) ? null : e; break; }
    }
    if (!paso) {
      esconder();
      if (actual !== 'nada') { actual = 'nada'; corto.textContent = 'Un momento…'; }
      return;
    }
    if (el && visible(el)) colocar(el); else esconder();

    if (actual !== paso.id) {
      actual = paso.id; quieto = 0;
      corto.textContent = paso.corto;
      window.__ultimaVoz = paso.voz;
      decir(paso.voz, false);
    } else {
      quieto++;
      if (quieto === 14) { decir(paso.voz, true); quieto = 0; }
    }
  }

  crear();
  latido();
  setInterval(latido, 1400);
  window.addEventListener('scroll', function () {
    for (var i = 0; i < GUION.length; i++) {
      var e = GUION[i].buscar();
      if (e && e !== true && visible(e)) { colocar(e); break; }
    }
  }, true);
})();
