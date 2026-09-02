/* JARVIS HUD service worker — 앱 셸 프리캐시 + 오프라인 폴백.
 *
 * 원칙:
 *  - /ws, /api 는 절대 캐시하지 않는다 (WebSocket·실시간 상태).
 *  - 셸은 cache-first (오프라인에서도 HUD가 뜬다), 그 외 same-origin GET은 network-first.
 *  - SHELL_VERSION 을 올리면 이전 캐시가 activate 단계에서 정리된다.
 *    index.html 의 ?v= 쿼리와 반드시 같이 올린다.
 */
const SHELL_VERSION = '2026090201';
const CACHE = `jarvis-shell-${SHELL_VERSION}`;

const SHELL = [
  './',
  'index.html',
  `styles.css?v=${SHELL_VERSION}`,
  `hud.js?v=${SHELL_VERSION}`,
  `voice.js?v=${SHELL_VERSION}`,
  `app.js?v=${SHELL_VERSION}`,
  'manifest.json',
  'icons/icon-192.png',
  'icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // 개별 실패가 설치 전체를 막지 않도록 하나씩 담는다(폰트 CDN 등 외부 자원 제외).
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isShellRequest(url) {
  const path = url.pathname.replace(/^\/+/, '');
  return (
    path === '' ||
    path === 'index.html' ||
    path === 'manifest.json' ||
    /^(styles\.css|hud\.js|voice\.js|app\.js)$/.test(path) ||
    path.startsWith('icons/')
  );
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // 폰트 등 외부 자원은 브라우저에 맡긴다
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return;

  // 내비게이션: 네트워크 우선, 끊기면 캐시된 셸로 폴백.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put('index.html', copy));
          return resp;
        })
        .catch(() => caches.match('index.html').then((r) => r || caches.match('./')))
    );
    return;
  }

  if (isShellRequest(url)) {
    // 셸 자산: 캐시 우선 + 백그라운드 갱신.
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((resp) => {
            if (resp && resp.ok) {
              const copy = resp.clone();
              caches.open(CACHE).then((c) => c.put(request, copy));
            }
            return resp;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
