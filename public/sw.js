const CACHE = 'optimap-v4';
const ASSETS = ['/', '/companies.json', '/manifest.json', '/icon-192.png', '/icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))); self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', e => {
  // Only handle same-origin requests — let cross-origin (mapbox, osrm, etc.) pass through
  if (!e.request.url.startsWith(self.location.origin)) return;
  if (e.request.url.match(/\.(js|css|png|woff2?)$/)) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => { const c = res.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); return res; })).catch(() => caches.match(e.request)));
    return;
  }
  if (e.request.url.includes('/companies.json')) {
    e.respondWith(fetch(e.request).then(res => { const c = res.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); return res; }).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});