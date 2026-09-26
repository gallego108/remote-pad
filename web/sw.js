/* Service worker de RemotePad.
 *
 * Historia: la primera version guardaba TODO en cache. Al anadir el acceso por
 * QR, el celular seguia ejecutando el app.js antiguo guardado en el telefono:
 * la pagina cargaba, pedia el PIN y nunca intentaba el canje del QR.
 *
 * Ahora la estrategia es "red primero" (si hay conexion manda el servidor; la
 * cache solo es respaldo sin conexion) y, al activarse una version nueva, se
 * avisa a las pestanas abiertas para que se recarguen solas.
 */

const CACHE = 'remotepad-v3';
const FILES = [
  './',
  'index.html',
  'styles.css',
  'app.js',
  'manifest.webmanifest',
  'icon-192.png',
  'icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ type: 'window' }))
      .then((clients) => {
        // Avisa a las pestanas abiertas de que hay version nueva.
        clients.forEach((client) => client.postMessage({ tipo: 'version-nueva' }));
      })
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;            // el canje del QR es POST
  if (request.url.includes('/ws')) return;         // el WebSocket no se toca
  if (request.url.includes('/qr')) return;         // panel de la PC, sin cache
  if (request.url.includes('?k=')) return;         // enlace del QR: siempre fresco

  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('index.html')))
  );
});
