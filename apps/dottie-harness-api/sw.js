const CACHE = 'dottie-v68-fail-closed-api';
const OFFLINE = '/offline.html';
const STATIC_ASSETS = [OFFLINE, '/', '/index.html', '/manifest.json'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter(cacheName => cacheName !== CACHE)
        .map(cacheName => caches.delete(cacheName))
    );

    const cache = await caches.open(CACHE);
    const requests = await cache.keys();
    await Promise.all(
      requests
        .filter(request => {
          const url = new URL(request.url);
          return url.pathname === '/api' || url.pathname.startsWith('/api/');
        })
        .map(request => cache.delete(request))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return;
  if (event.request.method !== 'GET') return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(event.request);
    if (cached) return cached;
    try {
      return await fetch(event.request);
    } catch {
      return cache.match(OFFLINE);
    }
  })());
});
