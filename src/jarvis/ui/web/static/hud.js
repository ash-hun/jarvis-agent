'use strict';

// ── Reactor HUD ───────────────────────────────────────────────────────────────
// 화면 중앙 엠블럼의 2D 레이어: 빛나는 바깥 링 + 위·아래 눈금 호 + 원판 가운데 어둡게 처리.
// 레이어 순서(아래→위): 입자 구(sphere.js, WebGL) → 이 캔버스 → 워드마크(DOM .reactor-wordmark).
// 색은 전부 에이전트 브랜드(window.BRAND.palette, /brand.js)에서 온다.
// 상태(HUD.setState)는 링 발광·눈금 점등·상태 라벨을 바꾸고, 입자 구는 HUD.state/level 을 읽어 따라간다.

// ── Brand palette ─────────────────────────────────────────────────────────────
const PALETTE = Object.assign(
  { primary: '#5fc8e2', accent: '#f0b35f', background: '#02060c',
    nebula: ['#3a5bff', '#8a4dff', '#ff6ad5'] },
  (window.BRAND && window.BRAND.palette) || {},
);

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mixRgb(a, b, t) {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}
function rgba(c, a) {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

const WHITE = [255, 255, 255];
const COL = {
  primary: hexToRgb(PALETTE.primary),
  accent:  hexToRgb(PALETTE.accent),
  red:     [240, 95, 95],
  nebula:  PALETTE.nebula.map(hexToRgb),
};
COL.bright = mixRgb(COL.primary, WHITE, 0.38);
COL.dim    = mixRgb(COL.primary, [0, 0, 0], 0.48);

const REDUCED_MOTION =
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const DPR = Math.min(2, window.devicePixelRatio || 1);

// ── Canvases ──────────────────────────────────────────────────────────────────
const canvas = document.getElementById('hud-canvas');
const ctx    = canvas.getContext('2d');
const stars  = document.getElementById('starfield');

function fitCanvas() {
  canvas.width  = Math.max(1, canvas.clientWidth)  * DPR;
  canvas.height = Math.max(1, canvas.clientHeight) * DPR;
}

// 별 배경 — 크기가 바뀔 때만 한 번 그린다.
function drawStarfield() {
  if (!stars) return;
  const w = window.innerWidth, h = window.innerHeight;
  stars.width = w * DPR;
  stars.height = h * DPR;
  const s = stars.getContext('2d');
  s.scale(DPR, DPR);
  const count = Math.round((w * h) / 2600);
  for (let i = 0; i < count; i++) {
    const tint = Math.random();
    const c = tint < 0.08 ? COL.nebula[i % COL.nebula.length]
            : tint < 0.2  ? COL.bright
            : WHITE;
    s.fillStyle = rgba(c, (0.15 + Math.random() * 0.6).toFixed(2));
    s.beginPath();
    s.arc(Math.random() * w, Math.random() * h, 0.3 + Math.random() * 0.9, 0, Math.PI * 2);
    s.fill();
  }
}

// 레이아웃(그리드·미디어쿼리)이 캔버스 크기를 정하므로 요소 자체를 관찰한다.
if ('ResizeObserver' in window) {
  new ResizeObserver(fitCanvas).observe(canvas);
} else {
  window.addEventListener('resize', fitCanvas);
}
window.addEventListener('resize', drawStarfield);
fitCanvas();
drawStarfield();

// ── State ─────────────────────────────────────────────────────────────────────
let hudState    = 'idle';
let level       = 0;     // 0‥1 활동량 — 링 발광·눈금 점등
let targetLevel = 0;
let speed       = 0.5;   // 회전 속도 배율
let phase       = 0;     // 누적 회전 위상 (속도가 바뀌어도 끊기지 않게)
let lastTs      = 0;

const STATE_SPEED = {
  idle: 0.5, listening: 0.8, thinking: 1.7, tool_running: 1.3, speaking: 1.1, error: 0.35,
};
// 링 아래 상태 라벨
const STATE_LABEL = {
  idle: 'ACTIVE', listening: 'LISTENING', thinking: 'THINKING',
  tool_running: 'EXECUTING', speaking: 'SPEAKING', error: 'ERROR',
};
const $status = document.getElementById('reactor-status');

let _simT = 0;
function simulate() {
  _simT += 0.06;
  if (hudState === 'thinking' || hudState === 'tool_running') {
    targetLevel = Math.max(0.1, Math.min(1,
      0.45 + 0.3 * Math.sin(_simT * 2.1) + 0.15 * Math.sin(_simT * 4.4)));
  } else if (hudState === 'error') {
    targetLevel = 0.2 + 0.1 * Math.sin(_simT * 3);
  } else if (hudState === 'listening') {
    targetLevel = 0.25 + 0.1 * Math.sin(_simT * 1.4);
  } else if (hudState === 'speaking') {
    targetLevel = 0.35 + 0.3 * Math.abs(Math.sin(_simT * 3.2));
  } else {
    targetLevel = 0.08 + Math.max(0, Math.sin(_simT * 0.6)) * 0.06;
  }
}
setInterval(simulate, 60);

// ── Drawing ───────────────────────────────────────────────────────────────────
// 반지름 기준(R=1): 바깥 링 0.9 · 가는 링 0.8 · 눈금 호 0.66‥0.74 · 안쪽 링 0.62 · 원판 0.6
const CORE_R = 0.6;

function drawRings(R, ph) {
  const lineCol = hudState === 'error' ? COL.red : COL.primary;
  const glow = 0.55 + level * 0.9;

  // 1. 두꺼운 바깥 링 — 발광이 활동량에 따라 숨쉰다
  ctx.strokeStyle = rgba(lineCol, 0.95);
  ctx.lineWidth = R * 0.055;
  ctx.shadowColor = rgba(lineCol, 1);
  ctx.shadowBlur = R * 0.09 * glow;
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.9, 0, Math.PI * 2);
  ctx.stroke();
  // 링 위를 도는 밝은 하이라이트
  ctx.strokeStyle = rgba(WHITE, 0.35 + level * 0.3);
  ctx.lineWidth = R * 0.02;
  ctx.shadowBlur = R * 0.04;
  const hl = ph * 0.2;
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.9, hl, hl + 0.5);
  ctx.stroke();
  ctx.shadowBlur = 0;

  // 2. 가는 링 두 줄
  ctx.strokeStyle = rgba(COL.primary, 0.55);
  ctx.lineWidth = Math.max(1, R * 0.006);
  for (const r of [0.8, CORE_R + 0.02]) {
    ctx.beginPath();
    ctx.arc(0, 0, R * r, 0, Math.PI * 2);
    ctx.stroke();
  }

  // 3. 위·아래 눈금 호 — 스캐너처럼 한 칸씩 밝아진다(활동 중일수록 빠르고 넓게)
  const ticks = 22;
  const span = Math.PI * 0.42;              // 각 호가 차지하는 각도
  const lit = (ph * 6) % ticks;
  ctx.lineWidth = Math.max(1.5, R * 0.014);
  for (const center of [-Math.PI / 2, Math.PI / 2]) {
    for (let i = 0; i < ticks; i++) {
      const a = center - span / 2 + (i / (ticks - 1)) * span;
      const d = Math.min(Math.abs(i - lit), ticks - Math.abs(i - lit));
      const on = Math.max(0, 1 - d / (1.5 + level * 4));
      ctx.strokeStyle = rgba(on > 0 ? COL.bright : COL.dim, 0.45 + on * 0.55);
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * R * 0.665, Math.sin(a) * R * 0.665);
      ctx.lineTo(Math.cos(a) * R * 0.745, Math.sin(a) * R * 0.745);
      ctx.stroke();
    }
    // 호 양 끝의 브래킷
    ctx.strokeStyle = rgba(COL.primary, 0.8);
    ctx.lineWidth = R * 0.01;
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.775, center - span / 2 - 0.08, center - span / 2 + 0.05);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.775, center + span / 2 - 0.05, center + span / 2 + 0.08);
    ctx.stroke();
  }
}

// 원판 가운데를 어둡게 — 뒤의 입자 구(sphere.js)가 밝아져도 워드마크가 읽히게 한다
function drawHush(R) {
  const coreR = R * CORE_R;
  const hush = ctx.createRadialGradient(0, 0, 0, 0, 0, coreR * 0.62);
  hush.addColorStop(0,    rgba(mixRgb(COL.primary, [0, 0, 0], 0.88), 0.72));
  hush.addColorStop(0.55, rgba(mixRgb(COL.primary, [0, 0, 0], 0.88), 0.45));
  hush.addColorStop(1,    rgba(mixRgb(COL.primary, [0, 0, 0], 0.88), 0));
  ctx.fillStyle = hush;
  ctx.fillRect(-coreR, -coreR, coreR * 2, coreR * 2);
}

function draw(ts) {
  const dt = lastTs ? Math.min(0.1, (ts - lastTs) / 1000) : 0;
  lastTs = ts;

  const targetSpeed = REDUCED_MOTION ? 0 : (STATE_SPEED[hudState] ?? 0.5);
  speed  += (targetSpeed - speed) * 0.05;
  level  += (targetLevel - level) * 0.1;
  phase  += dt * speed;
  const w = canvas.width, h = canvas.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.translate(w / 2, h / 2);
  const R = (Math.min(w, h) / 2) * 0.92;  // 바깥 링 발광이 잘리지 않도록 여유

  drawHush(R);
  drawRings(R, phase);

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// ── Public API ────────────────────────────────────────────────────────────────
window.HUD = {
  // sphere.js 가 매 프레임 읽는다
  get state() { return hudState; },
  get level() { return level; },
  setState(s) {
    hudState = s;
    // 상태 라벨·워드마크 톤은 CSS 가 data-state 로 처리한다
    document.querySelector('.sphere-wrap')?.setAttribute('data-state', s);
    if ($status) $status.textContent = STATE_LABEL[s] || s.toUpperCase();
    $status?.setAttribute('data-state', s);
  },
};
window.HUD.setState('idle');
