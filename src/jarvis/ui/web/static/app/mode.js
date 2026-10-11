// HUD 모드(Default / Full-voice) — 헤더 세그먼트가 고르고 body[data-mode] 와 localStorage 에 남긴다.
const MODES = ['default', 'full-voice'];
const DEFAULT_MODE = 'default';
const STORAGE_KEY = 'hud.mode';

const $seg = document.getElementById('mode-seg');

let _mode = DEFAULT_MODE;
const _listeners = [];

export function currentMode() { return _mode; }
export function isFullVoice() { return _mode === 'full-voice'; }
export function onModeChange(fn) { _listeners.push(fn); }

function apply(mode) {
  _mode = mode;
  document.body.dataset.mode = mode;
  $seg.querySelectorAll('[data-mode]').forEach((b) => {
    b.setAttribute('aria-checked', b.dataset.mode === mode ? 'true' : 'false');
  });
}

// 같은 모드를 다시 고르면 아무 일도 없다. 모르는 값은 무시한다.
export function setMode(mode) {
  if (!MODES.includes(mode) || mode === _mode) return;
  apply(mode);
  try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* storage 차단 — 이번 탭에서만 유지 */ }
  _listeners.forEach((fn) => fn(mode));
}

let _saved = DEFAULT_MODE;
try { _saved = localStorage.getItem(STORAGE_KEY) || DEFAULT_MODE; } catch { /* 기본 모드로 */ }
apply(MODES.includes(_saved) ? _saved : DEFAULT_MODE);

$seg.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-mode]');
  if (btn) setMode(btn.dataset.mode);
});
