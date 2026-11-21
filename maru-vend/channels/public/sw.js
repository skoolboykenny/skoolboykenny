// Maru app service worker: caches the app shell so it opens instantly and offline.
// API calls always go to the network: tokens and prices are never served from cache.
const CACHE = 'maru-app-v1';
const SHELL = ['/app', '/assets/maru.css', '/assets/store.js', '/assets/logo.png', '/assets/icon-192.png'];
self.addEventListener('install', (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))));
self.addEventListener('activate', (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
));
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
