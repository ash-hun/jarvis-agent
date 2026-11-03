// 에이전트 전환 — 구체 좌우의 화살표와 구체 밀기. 구체가 밀려 나가고 다음 에이전트의 구체가 반대편에서 들어온다.
import { agents, isTeam } from './agents.js';
import { AGENT_ID } from './brand.js';

const OUT_MS = 220;
const IN_MS = 360;
const SHIFT = '38%';         // 구체 지름 대비 밀리는 거리
const SWIPE_MIN_PX = 48;     // 이보다 짧게 밀면 클릭(듣기)으로 본다
const BRAND_WAIT_MS = 1500;  // 새 세션이 붙어 색이 바뀔 때까지 기다리는 상한

const $wrap = document.querySelector('.sphere-wrap');
const $prev = document.getElementById('agent-prev');
const $next = document.getElementById('agent-next');
const $hit = document.getElementById('sphere-hit');
// 밀려 나가는 것: 링과 별(2D), 입자 구(WebGL), 워드마크. 화살표와 클릭 영역은 제자리에 둔다
const $layers = ['#sphere-gl', '#hud-canvas', '.reactor-wordmark'].map((s) => $wrap.querySelector(s));
const _motion = window.matchMedia('(prefers-reduced-motion: reduce)');

let _switch = null;   // session.js 가 넘긴 전환 함수(agentId) => Promise
let _busy = false;

export function setAgentSwitcher(fn) { _switch = fn; }

// 지금 에이전트에서 step(±1)만큼 옮긴 에이전트. 끝에서는 반대 끝으로 돈다
function neighbor(step) {
  const list = agents();
  const i = list.findIndex((a) => a.id === AGENT_ID);
  return list[(i + step + list.length) % list.length] || null;
}

function label($btn, agent) {
  $btn.dataset.agent = agent.id;
  $btn.style.setProperty('--agent-color', agent.palette.primary);
  $btn.setAttribute('aria-label', `${agent.name} 으로 전환`);
  $btn.title = agent.name;
}

// 세션에 붙을 때마다 부른다. 에이전트가 하나면 화살표를 숨긴다
export function renderAgentNav() {
  const team = isTeam();
  $prev.hidden = !team;
  $next.hidden = !team;
  if (!team) return;
  label($prev, neighbor(-1));
  label($next, neighbor(1));
}

function play(frames, ms, easing) {
  return Promise.all($layers.map((el) => el.animate(frames, { duration: ms, easing, fill: 'forwards' }).finished))
    .catch(() => {});
}

function waitForBrand() {
  return new Promise((resolve) => {
    const done = () => { clearTimeout(timer); window.removeEventListener('jarvis:palette', done); resolve(); };
    const timer = setTimeout(done, BRAND_WAIT_MS);
    window.addEventListener('jarvis:palette', done);
  });
}

// step 쪽 에이전트로 옮긴다. 다음 에이전트가 오른쪽(step 1)에서 들어오니 지금 구체는 왼쪽으로 나간다
async function swipe(step) {
  if (_busy || !_switch || !isTeam()) return;
  const target = neighbor(step);
  if (!target) return;
  _busy = true;
  const out = step > 0 ? `-${SHIFT}` : SHIFT;
  const enter = step > 0 ? SHIFT : `-${SHIFT}`;
  try {
    if (_motion.matches) { await _switch(target.id); return; }
    await play([{ translate: '0 0', opacity: 1 }, { translate: `${out} 0`, opacity: 0 }], OUT_MS, 'cubic-bezier(.5,0,.9,.6)');
    const brand = waitForBrand();
    const moved = await _switch(target.id);
    if (moved) await brand;
    // 옮기지 못했으면(세션 생성 실패) 나간 쪽에서 되돌아온다
    const from = moved ? enter : out;
    await play([{ translate: `${from} 0`, opacity: 0 }, { translate: '0 0', opacity: 1 }], IN_MS, 'cubic-bezier(.15,.7,.2,1)');
  } finally {
    $layers.forEach((el) => el.getAnimations().forEach((a) => a.cancel()));
    _busy = false;
  }
}

$prev.addEventListener('click', () => swipe(-1));
$next.addEventListener('click', () => swipe(1));

// 구체를 좌우로 밀면 전환한다. 짧게 누르면 그대로 클릭(듣기)이다
let _start = null;
let _swallowClick = false;
$wrap.addEventListener('pointerdown', (e) => {
  if (!isTeam() || e.target.closest('.agent-nav')) return;
  _start = { x: e.clientX, y: e.clientY };
});
$wrap.addEventListener('pointerup', (e) => {
  if (!_start) return;
  const dx = e.clientX - _start.x;
  const dy = e.clientY - _start.y;
  _start = null;
  if (Math.abs(dx) < SWIPE_MIN_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return;
  _swallowClick = true;
  setTimeout(() => { _swallowClick = false; }, 400);  // 구체 밖에서 손을 뗐으면 클릭이 오지 않는다
  swipe(dx < 0 ? 1 : -1);  // 왼쪽으로 밀면 오른쪽(다음) 에이전트가 들어온다
});
$wrap.addEventListener('pointercancel', () => { _start = null; });
// 민 뒤 따라오는 클릭이 듣기를 켜지 않게 한 번 삼킨다
$hit.addEventListener('click', (e) => {
  if (!_swallowClick) return;
  _swallowClick = false;
  e.stopImmediatePropagation();
}, { capture: true });
