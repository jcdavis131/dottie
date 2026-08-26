// PWA v67 — offline13k CORE20 — no-cache header via vercel.json
const CACHE = "arxiviq-v67-20260813";
const OFFLINE = ["/dottie", "/conductor", "/manifest.json"];
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(OFFLINE).catch(() => {}))
  );
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/data/")) {
    e.respondWith(
      caches.open(CACHE).then(async (c) => {
        const cached = await c.match(e.request);
        const fetchP = fetch(e.request).then((r) => {
          if (r.ok) c.put(e.request, r.clone());
          return r;
        }).catch(() => cached);
        return cached || fetchP;
      })
    );
    return;
  }
  if (OFFLINE.some(p => url.pathname === p || url.pathname.startsWith(p))) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request).then(r => r || caches.match("/dottie")))
    );
    return;
  }
});
