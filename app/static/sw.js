// Service Worker para PWA Pollo Apanado
const CACHE_NAME = 'pollo-apanado-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // PWA minimal fetch handler para permitir instalación en Android/Chrome
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
