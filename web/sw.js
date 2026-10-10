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

const CACHE = 'remotepad-v8';
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
  if (request.url.includes('?k=')) return;         // enlace del QR: fresco
  if (request.url.includes('?v=')) return;         // recarga forzada: fresca

  // El codigo de la aplicacion se pide SIEMPRE a la red: es lo que evita que
  // el celular se quede con un app.js antiguo (el fallo mas costoso de
  // encontrar de todo el proyecto: la pagina cargaba y el servidor recibia
  // acciones que ya no existian).
  const critico = request.destination === 'script'
    || request.destination === 'style'
    || request.destination === 'document'
    || request.url.endsWith('app.js')
    || request.url.endsWith('styles.css');

  if (critico) {
    event.respondWith(
      fetch(request, { cache: 'no-store' })
        .catch(() => caches.match(request))
    );
    return;
  }

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
