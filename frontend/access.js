/*
 * Puerta de entrada compartida a toda la app (index.html, city.html,
 * debate.html): pide UNA clave (la que reparte Fran a mano), la recuerda en
 * este navegador (localStorage) y la manda en cada peticion como token de
 * visitante. Ver el backend en app/core/access.py.
 *
 * Entrar la clave correcta en cualquiera de las 3 paginas desbloquea las
 * demas (mismo origen -> mismo localStorage). Sin ACCESS_CODE configurada
 * en el servidor la puerta esta abierta (para desarrollar en local) y esto
 * no llega a mostrar nada.
 */
const AIAccess = (() => {
  const TOKEN_KEY = "aic_token";
  let resolveReady;
  const readyPromise = new Promise((res) => { resolveReady = res; });

  function apiBase() {
    const host = window.AI_COUNCIL_HOST || location.host || "localhost:8000";
    return (location.protocol === "https:" ? "https://" : "http://") + host;
  }

  function getToken() { return localStorage.getItem(TOKEN_KEY); }
  function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }

  /** Como fetch(), pero anade el header de autenticacion automaticamente.
   * Si el servidor responde 401 (p.ej. Fran cambio la clave y este token
   * ya no vale), se borra el token guardado y se recarga la pagina para
   * que vuelva a pedir la clave, en vez de dejar la app rota en silencio. */
  async function authFetch(url, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    const t = getToken();
    if (t) headers["X-Visitor-Token"] = t;
    const r = await fetch(url, Object.assign({}, opts, { headers }));
    if (r.status === 401 && t) {
      localStorage.removeItem(TOKEN_KEY);
      location.reload();
    }
    return r;
  }

  /** Trocito para pegar al final de una URL de WebSocket: "" o "?visitor=...". */
  function wsParam() {
    const t = getToken();
    return t ? "?visitor=" + encodeURIComponent(t) : "";
  }

  function buildLock() {
    const wrap = document.createElement("div");
    wrap.id = "aicLock";
    wrap.innerHTML = `
      <style>
        #aicLock { position:fixed; inset:0; z-index:9999; display:grid; place-items:center;
          background: radial-gradient(1200px 700px at 80% -10%, rgba(124,92,255,.35), transparent 60%),
                      radial-gradient(900px 600px at -10% 20%, rgba(32,197,255,.22), transparent 55%),
                      linear-gradient(160deg, #0a0b16, #12132a 55%, #1a1140);
          font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
          padding:20px; box-sizing:border-box; }
        #aicLock * { box-sizing:border-box; }
        #aicLock .card { width:100%; max-width:340px; background:rgba(28,30,54,.75);
          border:1px solid rgba(255,255,255,.12); border-radius:20px; padding:28px 24px;
          backdrop-filter:blur(16px); text-align:center; color:#eef1fb; }
        #aicLock .ic { font-size:38px; margin-bottom:6px; }
        #aicLock h2 { font-size:17px; margin:0 0 6px; }
        #aicLock p { font-size:12.5px; color:#a2a7c4; margin:0 0 18px; line-height:1.5; }
        #aicLock input { width:100%; padding:12px 14px; border-radius:12px;
          border:1px solid rgba(255,255,255,.15); background:#ffffff0d; color:#eef1fb;
          font-size:15px; outline:none; text-align:center; letter-spacing:.05em; }
        #aicLock input:focus { border-color:rgba(255,255,255,.35); }
        #aicLock button { width:100%; margin-top:12px; padding:12px; border-radius:12px;
          border:none; cursor:pointer; font-size:14px; font-weight:600; color:#fff;
          background:linear-gradient(135deg,#7c5cff,#20c5ff); }
        #aicLock button:disabled { opacity:.5; cursor:not-allowed; }
        #aicLock .err { color:#ff5ca8; font-size:12px; margin-top:10px; min-height:16px; }
      </style>
      <div class="card">
        <div class="ic">🔐</div>
        <h2>Ciudad IA</h2>
        <p>Introduce la clave de acceso que te ha dado Fran.</p>
        <input id="aicCode" type="text" inputmode="text" autocomplete="off" placeholder="Clave de acceso" />
        <button id="aicSubmit">Entrar</button>
        <div class="err" id="aicErr"></div>
      </div>`;
    document.body.appendChild(wrap);

    const input = wrap.querySelector("#aicCode");
    const btn = wrap.querySelector("#aicSubmit");
    const err = wrap.querySelector("#aicErr");

    async function submit() {
      const code = input.value.trim();
      if (!code) return;
      btn.disabled = true;
      err.textContent = "";
      try {
        const r = await fetch(apiBase() + "/access/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        if (!r.ok) {
          err.textContent = "Clave incorrecta.";
          btn.disabled = false;
          input.focus();
          return;
        }
        const data = await r.json();
        setToken(data.token);
        wrap.remove();
        resolveReady();
      } catch (e) {
        err.textContent = "No se pudo comprobar la clave. Revisa tu conexion.";
        btn.disabled = false;
      }
    }
    btn.onclick = submit;
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    setTimeout(() => input.focus(), 50);
  }

  async function init() {
    if (getToken()) { resolveReady(); return; }
    try {
      const r = await fetch(apiBase() + "/access/status");
      const data = await r.json();
      if (!data.gate_enabled) {
        // Puerta abierta (desarrollo local, sin ACCESS_CODE): cada
        // navegador se inventa su propio id para tener su sala separada,
        // sin tener que pedir ninguna clave.
        setToken("dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36));
        resolveReady();
        return;
      }
    } catch (e) {
      // Si ni siquiera se pudo preguntar, se pide la clave igualmente:
      // sin ella no hay forma de saber si la puerta esta activada o no.
    }
    buildLock();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { ready: () => readyPromise, fetch: authFetch, wsParam, getToken };
})();
