// 헤더·리액터 캡션·Activity·카드 접기·드로어 — 대화 밖의 HUD 외피.
import { QUOTE } from './brand.js';

const $clock       = document.getElementById('clock');
const $statusText  = document.getElementById('status-text');
const $statusPill  = document.getElementById('status-pill');
const $uptime      = document.getElementById('uptime');
const $caption     = document.getElementById('reactor-caption');
const $activityLog = document.getElementById('activity-log');
const $drawerBtn   = document.getElementById('drawer-btn');
const $drawerScrim = document.getElementById('drawer-scrim');

export const CAPTION_HOLD_MS = 20000;
const ACTIVITY_MAX = 60;
const DRAWER_MAX_WIDTH = 860;  // styles.css 의 @media (max-width: 860px) 와 같은 값

// ── Clock · Uptime ────────────────────────────────────────────────────────────
const pad = (n) => String(n).padStart(2, '0');
const _startTime = Date.now();

function updateClock() {
  const d = new Date();
  $clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function updateUptime() {
  const s = Math.floor((Date.now() - _startTime) / 1000);
  $uptime.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}
setInterval(updateClock, 1000);
setInterval(updateUptime, 1000);
updateClock();
updateUptime();

// ── Status pill ───────────────────────────────────────────────────────────────
export function setStatus(label, cls = '') {
  $statusText.textContent = label;
  $statusPill.className   = 'status-pill' + (cls ? ' ' + cls : '');
}
export function currentStatus() { return $statusText.textContent; }

// ── Reactor caption ───────────────────────────────────────────────────────────
// 쉴 때는 명언, 응답·proactive 메시지가 오면 그 한 줄. 잠시 뒤 명언으로 돌아간다.
let _captionTimer = null;

function setCaption(text, kind) {
  const swap = () => {
    $caption.className = `reactor-caption ${kind}`;
    $caption.textContent = text;
  };
  if ($caption.classList.contains(kind)) { swap(); return; }
  $caption.classList.add('fading');
  setTimeout(swap, 350);
}

export function showQuote() {
  clearTimeout(_captionTimer);
  setCaption(QUOTE, 'quote');
}

export function showLive(text, holdMs = 0) {
  clearTimeout(_captionTimer);
  setCaption(text, 'live');
  if (holdMs) _captionTimer = setTimeout(showQuote, holdMs);
}

// 마크다운 기호를 걷어낸 마지막 비어 있지 않은 줄
export function lastLine(text) {
  const lines = text.split('\n').map((l) => l.replace(/[#*`>_]/g, '').trim()).filter(Boolean);
  const line = lines.length ? lines[lines.length - 1] : '';
  return line.length > 160 ? line.slice(0, 157) + '…' : line;
}

// ── Activity log ──────────────────────────────────────────────────────────────
export function logActivity(text, kind = '') {
  const d  = new Date();
  const li = document.createElement('li');
  if (kind) li.className = kind;
  li.innerHTML = `<time>${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}</time><span class="msg-text"></span>`;
  const span = li.querySelector('.msg-text');
  span.textContent = text;
  span.title = text;
  $activityLog.prepend(li);
  while ($activityLog.children.length > ACTIVITY_MAX) $activityLog.lastElementChild.remove();
}

// ── Card collapse ─────────────────────────────────────────────────────────────
// 접힘 여부는 뷰어별 편의 설정이라 localStorage 에만 둔다(없어도 동작).
export function setupCollapse(toggleId, bodyClass, storageKey, onExpand) {
  try {
    if (localStorage.getItem(storageKey) === '1') document.body.classList.add(bodyClass);
  } catch { /* storage 차단 — 기본(펼침)으로 */ }
  document.getElementById(toggleId).addEventListener('click', (e) => {
    if (e.target.closest('button')) return;  // 헤더 안의 버튼(+)은 접기가 아니다
    const next = !document.body.classList.contains(bodyClass);
    document.body.classList.toggle(bodyClass, next);
    try { localStorage.setItem(storageKey, next ? '1' : '0'); } catch { /* 무시 */ }
    if (!next && onExpand) onExpand();
  });
}

// ── Mobile drawer ─────────────────────────────────────────────────────────────
// 좁은 화면에서 아젠다·활동·시스템 카드(.hud-side)는 오버레이 드로어가 된다.
// 데스크탑에서는 버튼이 숨겨져 있어 이 코드가 실행될 일이 없다.
function setDrawer(open) {
  document.body.classList.toggle('drawer-open', open);
  $drawerScrim.hidden = !open;
  $drawerBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  $drawerBtn.setAttribute('aria-label', open ? '패널 닫기' : '패널 열기');
}

$drawerBtn.addEventListener('click', () => setDrawer(!document.body.classList.contains('drawer-open')));
$drawerScrim.addEventListener('click', () => setDrawer(false));
// 세션을 고르면 드로어를 닫아 바로 대화로 돌아간다.
document.getElementById('session-list').addEventListener('click', () => setDrawer(false));
document.getElementById('new-session-btn').addEventListener('click', () => setDrawer(false));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setDrawer(false); });
// 데스크탑 폭으로 돌아오면 드로어 상태를 남기지 않는다.
window.addEventListener('resize', () => { if (window.innerWidth > DRAWER_MAX_WIDTH) setDrawer(false); });
