/* JARVIS HUD service worker — 앱 셸 프리캐시 + 오프라인 폴백.
 *
 * 원칙:
 *  - /ws, /api 는 절대 캐시하지 않는다 (WebSocket·실시간 상태).
 *  - 셸(index, css, js)은 네트워크 우선이고, 끊겼을 때만 캐시를 쓴다. 캐시 우선이면
 *    파일을 고쳐도 다음 로드까지 옛 셸이 보여 HTML 과 CSS 가 섞인다.
 *  - 그래서 버전 문자열이 없다. 네트워크에서 받는 것이 곧 최신이고 캐시는 받을 때마다 덮인다.
 *  - SHELL 목록은 tests/unit/test_web_server.py 가 static/ 의 실제 파일과 대조한다.
 */
const CACHE = 'jarvis-shell';

const SHELL = [
  './',
  'index.html',
  'styles.css',
  'hud.js',
  'voice.js',
  'sphere.js',
  'app/agenda.js',
  'app/api.js',
  'app/approval.js',
  'app/artifact.js',
  'app/brand.js',
  'app/composer.js',
  'app/events.js',
  'app/main.js',
  'app/markdown.js',
  'app/messages.js',
  'app/mode.js',
  'app/proactive.js',
  'app/reply.js',
  'app/session.js',
  'app/shell.js',
  'app/tools.js',
  'app/usage.js',
  'app/voice-ui.js',
  'app/ws.js',
  'vendor/three/three.module.min.js',
  'vendor/three/three.core.js',
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
    /\.(js|css)$/.test(path) ||
    path.startsWith('icons/')
  );
}

// 네트워크 우선: 받으면 캐시를 덮고, 실패하면(오프라인) 캐시로 폴백.
function networkFirst(request, fallbackKey) {
  return fetch(request)
    .then((resp) => {
      if (resp && resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(fallbackKey || request, copy));
      }
      return resp;
    })
    .catch(() => caches.match(fallbackKey || request).then((r) => r || caches.match('./')));
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // 폰트 등 외부 자원은 브라우저에 맡긴다
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, 'index.html'));
    return;
  }
  if (isShellRequest(url)) event.respondWith(networkFirst(request));
});
