// Minimal service worker for Balance.
//
// Its job is to make Balance a fully installable PWA (a registered SW with a
// fetch handler) and to pre-cache the small static shell (icons + manifest).
// Balance itself is a live, server-driven app (NiceGUI over a websocket), so
// it is intentionally NOT offline-capable -- the fetch handler only serves
// the handful of static assets from cache and passes everything else straight
// through to the network, never intercepting dynamic routes or the websocket.

const CACHE = "balance-shell-v1";
const ASSETS = [
  "/icon-assets/icon.png",
  "/icon-assets/icon-192.png",
  "/icon-assets/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method === "GET" && ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(event.request).then((r) => r || fetch(event.request)));
  }
  // All other requests (pages, websocket, API) use the default network path.
});
