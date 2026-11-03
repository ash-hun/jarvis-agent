// 화면 전환 — HUD, Workflow, Settings. body[data-view] 가 CSS 로 스테이지와 화면을 바꾼다.
// 바꿀 때 지금 화면의 카드가 기계 판처럼 덜컥 풀려 화면 밖으로 빠지고, 다음 화면의 카드가 반대편에서 밀려 들어와 걸린다.
const VIEWS = ['hud', 'workflow', 'settings'];
const STORE_KEY = 'hud.view';
const OUT_MS = 240;
const IN_MS = 420;
const STAGGER_MS = 45;
const $seg = document.getElementById('view-seg');
const _openers = new Map();
const _motion = window.matchMedia('(prefers-reduced-motion: reduce)');
let _view = 'hud';
let _moving = false;
let _queued = null;   // 움직이는 동안 누른 탭. 끝나면 마지막 것 하나로 간다

function readStored() {
  try { return localStorage.getItem(STORE_KEY); } catch { return null; }
}

export function currentView() { return _view; }

// 화면이 열릴 때마다 부를 함수. 화면 모듈이 자기 데이터를 다시 받는다
export function onViewOpen(view, fn) { _openers.set(view, fn); }

// 밑줄을 고른 탭 아래로 옮긴다. 탭 사이를 미끄러져 간다(CSS transition)
function markTabs(view) {
  let active = null;
  for (const btn of $seg.querySelectorAll('button[data-view]')) {
    const on = btn.dataset.view === view;
    btn.setAttribute('aria-checked', String(on));
    if (on) active = btn;
  }
  if (!active) return;
  $seg.style.setProperty('--tab-x', `${active.offsetLeft}px`);
  $seg.style.setProperty('--tab-w', `${active.offsetWidth}px`);
}

function apply(view) {
  _view = view;
  document.body.dataset.view = view;
  markTabs(view);
  for (const panel of document.querySelectorAll('[data-view-panel]')) {
    panel.hidden = panel.dataset.viewPanel !== view;
  }
  try { localStorage.setItem(STORE_KEY, view); } catch { /* 저장 못 해도 화면은 바뀐다 */ }
  const open = _openers.get(view);
  if (open) open();
}

// 화면을 이루는 판과 각자 빠질 방향. HUD 는 왼쪽 열은 왼쪽, 오른쪽 열은 오른쪽으로 빠지고 리액터는 안으로 접힌다.
// 다른 화면은 이동 방향(dir)을 따라 모두 같은 쪽으로 움직인다
function partsOf(view, dir) {
  if (view === 'hud') {
    return [
      ...[...document.querySelectorAll('.hud-side > .hud-card')].map((el) => ({ el, dir: -1 })),
      ...[...document.querySelectorAll('.chat-col > .hud-card')].map((el) => ({ el, dir: 1 })),
      { el: document.querySelector('.stage .reactor'), core: true },
    ];
  }
  const panel = document.querySelector(`[data-view-panel="${view}"]`);
  return panel ? [...panel.children].filter((el) => !el.hidden).map((el) => ({ el, dir })) : [];
}

// 나갈 때: 반대쪽으로 살짝 물러났다가(걸쇠가 풀리는 느낌) 화면 밖으로 빠진다
function outFrames(dir) {
  return [
    { translate: '0 0', opacity: 1 },
    { translate: `${-dir * 10}px 0`, opacity: 1, offset: 0.22, easing: 'cubic-bezier(.6,0,.9,.4)' },
    { translate: `${dir * 110}vw 0`, opacity: 0.4 },
  ];
}

// 들어올 때: 빠르게 밀려 들어와 조금 지나쳤다가 두 번에 걸쳐 제자리에 걸린다
function inFrames(dir) {
  return [
    { translate: `${dir * 110}vw 0`, opacity: 0.4, easing: 'cubic-bezier(.15,.75,.25,1)' },
    { translate: `${-dir * 12}px 0`, opacity: 1, offset: 0.78, easing: 'steps(2, end)' },
    { translate: '0 0', opacity: 1 },
  ];
}

const CORE_OUT = [{ scale: 1, opacity: 1 }, { scale: 0.82, opacity: 0 }];
const CORE_IN = [
  { scale: 0.82, opacity: 0, easing: 'cubic-bezier(.2,.8,.3,1)' },
  { scale: 1.02, opacity: 1, offset: 0.8, easing: 'steps(2, end)' },
  { scale: 1, opacity: 1 },
];

function play(parts, phase) {
  const anims = parts.map(({ el, dir, core }, i) => el.animate(
    core ? (phase === 'out' ? CORE_OUT : CORE_IN) : (phase === 'out' ? outFrames(dir) : inFrames(dir)),
    { duration: phase === 'out' ? OUT_MS : IN_MS, delay: i * STAGGER_MS, fill: phase === 'out' ? 'forwards' : 'backwards' },
  ));
  return { anims, done: Promise.all(anims.map((a) => a.finished)).catch(() => {}) };
}

async function transition(from, to) {
  _moving = true;
  // 다음 화면이 오른쪽 탭이면 지금 화면은 왼쪽으로 빠지고 다음 화면은 오른쪽에서 들어온다
  const dir = VIEWS.indexOf(to) > VIEWS.indexOf(from) ? 1 : -1;
  markTabs(to);
  const out = play(partsOf(from, -dir), 'out');
  await out.done;
  apply(to);
  out.anims.forEach((a) => a.cancel());  // 빠진 판은 숨었으니 제자리로 돌려 둔다
  await play(partsOf(to, dir), 'in').done;
  _moving = false;
  if (_queued) {
    const next = _queued;
    _queued = null;
    setView(next);
  }
}

export function setView(view) {
  if (!VIEWS.includes(view)) view = 'hud';
  if (_moving) { _queued = view; return; }
  if (view === _view && document.body.dataset.view === view) return;
  if (_motion.matches || document.body.dataset.view !== _view) { apply(view); return; }
  transition(_view, view);
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

// 글꼴이 늦게 와 탭 폭이 바뀌면 밑줄을 다시 맞춘다
window.addEventListener('resize', () => markTabs(_view));
document.fonts?.ready.then(() => markTabs(_view));

// 처음 열 때는 움직이지 않고 바로 그 화면으로
export function restoreView() {
  const stored = readStored();
  apply(VIEWS.includes(stored) ? stored : 'hud');
}
