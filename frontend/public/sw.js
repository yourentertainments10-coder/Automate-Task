/* CarTrends CRM service worker.
 *
 * Deliberately conservative: it caches the app shell so the app opens
 * instantly (and shows a proper offline page instead of a browser error),
 * but it NEVER caches API responses — business data must always be live.
 */
// The placeholder below is stamped by stamp-sw.mjs on every `npm run build`,
// so each deploy ships a byte-different sw.js -> installed apps detect the
// update and show the in-app "Update" button.
const VERSION = '__BUILD_VERSION__';
const CACHE = 'cartrends-shell-' + VERSION;
const SHELL = ['/', '/index.html', '/manifest.webmanifest',
               '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  // NO skipWaiting here: the new version waits until the user taps Update
  // (or closes the app) -- never yank the rug mid-use.
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})));
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Never serve business data from a cache.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) return;

  // Navigations: network first, fall back to the cached shell when offline.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Static assets: serve from cache, refresh in the background.
  event.respondWith(
    caches.match(request).then((hit) => {
      const network = fetch(request)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});
