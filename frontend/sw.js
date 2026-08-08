/* Service worker minimo: solo permite instalar la PWA y da un arranque
   rapido cacheando el "cascaron". Los datos de la ciudad (WebSocket y API)
   nunca se cachean: siempre van en directo al servidor para ver el estado
   real. */
const CACHE = "ciudad-ia-v16";
const SHELL = ["index.html", "city.html", "debate.html", "access.js", "manifest.webmanifest", "icon-192.png", "icon-512.png",
               "policia.html", "policia.webmanifest", "policia-192.png", "policia-512.png",
               "clases.html", "clases.webmanifest", "clases-192.png", "clases-512.png",
               "clinica.html", "clinica.webmanifest", "clinica-192.png", "clinica-512.png"];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Nunca cachear API ni websockets: siempre en vivo.
  // /policia y /clases NUNCA se cachean. Son documentos de trabajo: leer
  // una version guardada de hace dos dias y creer que es la de hoy seria
  // mucho peor que no poder abrirlo.
  if (e.request.method !== "GET" || url.pathname.startsWith("/city") ||
      url.pathname.startsWith("/conversations") ||
      url.pathname.startsWith("/ws") || url.pathname.startsWith("/providers") ||
      url.pathname.startsWith("/health") || url.pathname.startsWith("/access") ||
      url.pathname.startsWith("/policia/") || url.pathname.startsWith("/clases/") ||
      url.pathname.startsWith("/clinica/") ||
      url.pathname.startsWith("/guardian")) {
    return; // deja pasar a la red normal
  }
  // Cascaron: network-first con recaida a cache (para que actualice al desplegar).
  e.respondWith(
    fetch(e.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match(e.request))
  );
});
