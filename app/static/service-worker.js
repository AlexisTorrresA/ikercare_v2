const CACHE_NAME = 'ikercare-static-v2.0.0-v2.2.5';
const STATIC_ASSETS = [
  '/static/v2.css',
  '/static/v2.js',
  '/static/v2-report-download-fix.js',
  '/static/v2-clinical-history.js',
  '/static/v2-clinical-history.css',
  '/static/v2-clinical-preserve.js',
  '/static/v2-visible-care-fixes.js',
  '/static/v2-visible-care-actions.js',
  '/static/v2-medication-extras.js',
  '/static/v2-sos-today.js',
  '/static/manifest.webmanifest',
  '/static/icons/favicon-64.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || !url.pathname.startsWith('/static/')) return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
    if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(event.request, response.clone()));
    return response;
  })));
});
