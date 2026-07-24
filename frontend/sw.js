/* Service worker minimo: solo permite instalar la PWA y da un arranque
   rapido cacheando el "cascaron". Los datos de la ciudad (WebSocket y API)
   nunca se cachean: siempre van en directo al servidor para ver el estado
   real. */
const CACHE = "ciudad-ia-v2";
const SHELL = ["index.html", "city.html", "debate.html", "manifest.webmanifest", "icon-192.png", "icon-512.png"];

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
  if (e.request.method !== "GET" || url.pathname.startsWith("/city") ||
      url.pathname.startsWith("/conversations") ||
      url.pathname.startsWith("/ws") || url.pathname.startsWith("/providers") ||
      url.pathname.startsWith("/health")) {
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
