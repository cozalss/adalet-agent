/* ADALET PWA service worker — offline kabuk + kurulabilirlik.

   KVKK / sıfır-veri-cache KIRMIZI ÇİZGİ:
   - /ask, /api, /multimodal, /auth, /health, /metrics → ASLA cache'lenmez
     (yasal soru/cevap, dilekçe, oturum verisi cihazda tutulmaz). Network-only.
   - Yalnız STATİK uygulama kabuğu (HTML/CSS/JS/ikon/font) cache'lenir →
     uygulama offline'da açılır, ama cevap için backend gerekir.
   - POST istekleri (soru gönderme) her zaman network. */

const CACHE = "adalet-shell-v1";
const API_PREFIXES = ["/ask", "/api", "/multimodal", "/auth", "/health", "/metrics"];

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return; // soru gönderme (POST) → network
  const url = new URL(req.url);

  // KVKK: API yolları asla cache'lenmez — network-only.
  if (url.origin === location.origin && API_PREFIXES.some((p) => url.pathname.startsWith(p))) return;

  const sameOrigin = url.origin === location.origin;
  const isFont = url.hostname.includes("gstatic") || url.hostname.includes("googleapis");
  if (!sameOrigin && !isFont) return; // üçüncü taraf → dokunma

  // Statik kabuk + font → stale-while-revalidate (offline'da cache'ten servis).
  e.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((resp) => {
          if (resp && resp.status === 200 && resp.type !== "opaque") {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return resp;
        })
        .catch(() => cached || (req.mode === "navigate" ? caches.match("/") : undefined));
      return cached || network;
    })
  );
});
