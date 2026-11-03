// 화면 전환 — HUD, Workflow, Settings. body[data-view] 가 CSS 로 스테이지와 화면을 바꾼다.
const VIEWS = ['hud', 'workflow', 'settings'];
const STORE_KEY = 'hud.view';
const $seg = document.getElementById('view-seg');
const _openers = new Map();
let _view = 'hud';

function readStored() {
  try { return localStorage.getItem(STORE_KEY); } catch { return null; }
}

export function currentView() { return _view; }

// 화면이 열릴 때마다 부를 함수. 화면 모듈이 자기 데이터를 다시 받는다
export function onViewOpen(view, fn) { _openers.set(view, fn); }

export function setView(view) {
  if (!VIEWS.includes(view)) view = 'hud';
  _view = view;
  document.body.dataset.view = view;
  for (const btn of $seg.querySelectorAll('button[data-view]')) {
    btn.setAttribute('aria-checked', String(btn.dataset.view === view));
  }
  for (const panel of document.querySelectorAll('[data-view-panel]')) {
    panel.hidden = panel.dataset.viewPanel !== view;
  }
  try { localStorage.setItem(STORE_KEY, view); } catch { /* 저장 못 해도 화면은 바뀐다 */ }
  const open = _openers.get(view);
  if (open) open();
}

$seg.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-view]');
  if (btn) setView(btn.dataset.view);
});

// Esc 는 HUD 로 돌아간다. 입력 중이거나 읽기를 멈추는 Esc(voice-ui.js) 와 겹치지 않게 HUD 가 아닐 때만
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || _view === 'hud') return;
  if (e.target instanceof HTMLElement && e.target.closest('input, select, textarea')) return;
  setView('hud');
});

export function restoreView() { setView(readStored() || 'hud'); }
