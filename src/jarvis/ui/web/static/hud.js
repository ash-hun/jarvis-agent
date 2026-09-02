'use strict';

// ── Canvas ────────────────────────────────────────────────────────────────────
const canvas = document.getElementById('hud-canvas');
const ctx    = canvas.getContext('2d');
const DPR    = Math.min(2, window.devicePixelRatio || 1);

function fitCanvas() {
  const w = canvas.clientWidth  || 140;
  const h = canvas.clientHeight || 140;
  canvas.width  = w * DPR;
  canvas.height = h * DPR;
}
fitCanvas();
window.addEventListener('resize', fitCanvas);

// ── Fibonacci sphere (N=900) ──────────────────────────────────────────────────
const N      = 900;
const POINTS = [];
for (let i = 0; i < N; i++) {
  const t     = i / (N - 1);
  const phi   = Math.acos(1 - 2 * t);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  POINTS.push({
    x:      Math.sin(phi) * Math.cos(theta),
    y:      Math.sin(phi) * Math.sin(theta),
    z:      Math.cos(phi),
    jitter: Math.random() * 0.5 + 0.5,
  });
}

// ── Theme colors (CSS 변수를 그대로 따라간다 — 테마를 바꾸면 HUD도 따라간다) ──
function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
const THEME = {
  cyan:       cssVar('--cyan', '#5fc8e2'),
  cyanBright: cssVar('--cyan-bright', '#7df0ff'),
  cyanDim:    cssVar('--cyan-dim', '#2c7e95'),
  amber:      cssVar('--amber', '#f0b35f'),
};
const REDUCED_MOTION =
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// ── State ─────────────────────────────────────────────────────────────────────
let hudState    = 'idle';
// 유휴에는 로고, 활동(thinking/tool_running/listening/speaking/error) 중에는 구체.
// 0 = 구체만, 1 = 로고만. 프레임마다 목표값으로 이징해 크로스페이드된다.
let logoMix     = 1;
let level       = 0;
let targetLevel = 0;
let rotY        = 0;
const rotX      = -0.18;

let _simT = 0;
function simulate() {
  _simT += 0.06;
  if (hudState === 'thinking' || hudState === 'tool_running') {
    targetLevel = Math.max(0.1, Math.min(1,
      0.4 + 0.3 * Math.sin(_simT * 2.1) + 0.15 * Math.sin(_simT * 4.4)));
  } else if (hudState === 'error') {
    targetLevel = 0.15 + 0.1 * Math.sin(_simT * 3);
  } else if (hudState === 'listening') {
    targetLevel = 0.08 + 0.06 * Math.sin(_simT * 1.4);
  } else if (hudState === 'speaking') {
    targetLevel = 0.2 + 0.14 * Math.abs(Math.sin(_simT * 3.2));
  } else {
    targetLevel = 0.04 + Math.max(0, Math.sin(_simT * 0.6)) * 0.04;
  }
}
setInterval(simulate, 60);

// ── Wave function (two-layer 3-D sine for organic shape) ──────────────────────
function getWave(x, y, z, t) {
  const a = Math.sin(3.2 * x + t * 0.9)  * Math.cos(3.2 * y + t * 0.65) * Math.sin(2.8 * z + t * 0.5);
  const b = Math.sin(5.5 * x - t * 0.7)  * Math.cos(4.5 * z + t * 0.40);
  return (a + 0.3 * b) / 1.3;  // approx −1 … +1
}

// ── Color mapping ─────────────────────────────────────────────────────────────
// wave < 0  → deep blue
// wave ≈ 0  → cyan
// wave > 0  → purple/violet (peak = spray)
function lerpC(a, b, t) {
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}
const BLUE   = { r: 18,  g: 40,  b: 190 };
const CYAN   = { r: 95,  g: 200, b: 226 };
const PURPLE = { r: 130, g: 60,  b: 220 };
const BRIGHT = { r: 200, g: 150, b: 255 };

function waveColor(wave) {
  if (wave < 0) {
    return lerpC(BLUE, CYAN, (wave + 1));          // −1→0 : blue→cyan
  } else if (wave < 0.45) {
    return lerpC(CYAN, PURPLE, wave / 0.45);       //  0→0.45: cyan→purple
  } else {
    return lerpC(PURPLE, BRIGHT, (wave - 0.45) / 0.55); // 0.45→1: purple→bright
  }
}

// ── Rotation helpers ──────────────────────────────────────────────────────────
function rotateY(p, c, s) {
  return { x: p.x * c + p.z * s, y: p.y, z: -p.x * s + p.z * c };
}
function rotateX(p, c, s) {
  return { x: p.x, y: p.y * c - p.z * s, z: p.y * s + p.z * c };
}

// ── Logo (아크 리액터 엠블럼) ────────────────────────────────────────────────
// 유휴 상태의 정체성 레이어. 이미지를 로드하지 않고 절차적으로 그린다 —
// 어떤 DPR·크기에서도 선명하고, 테마 색과 상태에 반응한다.
function drawLogo(ts, alpha) {
  const w = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h / 2;
  const R  = Math.min(w, h) * 0.46;
  const t  = REDUCED_MOTION ? 0 : ts / 1000;
  const breathe = 1 + Math.sin(t * 0.9) * 0.012;

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.translate(cx, cy);
  // 사라질 때 살짝 커지며 빠진다(구체로 넘어가는 전환감).
  ctx.scale(breathe * (1 + (1 - alpha) * 0.06), breathe * (1 + (1 - alpha) * 0.06));
  ctx.lineCap = 'butt';

  // 바깥 눈금 링 — 60틱, 5칸마다 길게
  ctx.strokeStyle = THEME.cyanDim;
  ctx.lineWidth = Math.max(1, R * 0.012);
  for (let i = 0; i < 60; i++) {
    const a  = (i / 60) * Math.PI * 2 - t * 0.06;
    const r0 = R * (i % 5 === 0 ? 0.86 : 0.91);
    ctx.globalAlpha = alpha * (i % 5 === 0 ? 0.85 : 0.45);
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
    ctx.lineTo(Math.cos(a) * R * 0.97, Math.sin(a) * R * 0.97);
    ctx.stroke();
  }
  ctx.globalAlpha = alpha;

  // 바깥 얇은 테두리
  ctx.strokeStyle = THEME.cyanDim;
  ctx.lineWidth = Math.max(1, R * 0.01);
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.99, 0, Math.PI * 2);
  ctx.stroke();

  // 메인 굵은 아크 — 두 조각으로 끊어 회전시킨다
  const spin = t * 0.10;
  ctx.strokeStyle = THEME.cyan;
  ctx.shadowColor = THEME.cyan;
  ctx.shadowBlur  = R * 0.22;
  ctx.lineWidth   = R * 0.17;
  for (const [from, to] of [[-0.60, 0.30], [0.44, 1.36]]) {
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.70, from * Math.PI + spin, to * Math.PI + spin);
    ctx.stroke();
  }
  ctx.shadowBlur = 0;

  // 메인 아크 위의 밝은 진행 세그먼트 — 천천히 돈다
  ctx.strokeStyle = THEME.cyanBright;
  ctx.lineWidth   = R * 0.17;
  ctx.globalAlpha = alpha * 0.55;
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.70, spin * 3.1, spin * 3.1 + 0.34 * Math.PI);
  ctx.stroke();
  ctx.globalAlpha = alpha;

  // 앰버 액센트 아크 (왼쪽 바깥) — 원본 로고의 노란 브래킷
  ctx.strokeStyle = THEME.amber;
  ctx.lineWidth   = R * 0.05;
  ctx.shadowColor = THEME.amber;
  ctx.shadowBlur  = R * 0.12;
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.855, 0.62 * Math.PI, 0.96 * Math.PI);
  ctx.stroke();
  ctx.shadowBlur = 0;

  // 상단 인디케이터 5점 — 순차 점등(스캐너). 캔버스 0도는 3시 방향이라 -0.5π가 12시.
  const lit = Math.floor(t * 1.6) % 5;
  for (let i = 0; i < 5; i++) {
    const a = (-0.68 + i * 0.09) * Math.PI;
    const on = i === lit;
    ctx.globalAlpha = alpha * (on ? 1 : 0.42);
    ctx.fillStyle = THEME.amber;
    ctx.shadowColor = THEME.amber;
    ctx.shadowBlur = on ? R * 0.18 : 0;
    ctx.beginPath();
    ctx.arc(Math.cos(a) * R * 0.70, Math.sin(a) * R * 0.70, R * 0.035, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.shadowBlur = 0;
  ctx.globalAlpha = alpha;

  // 안쪽 링 + 세그먼트 블록 8개 (반대 방향 회전)
  ctx.strokeStyle = THEME.cyanDim;
  ctx.lineWidth = Math.max(1, R * 0.01);
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.52, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = THEME.cyan;
  ctx.lineWidth   = R * 0.035;
  ctx.globalAlpha = alpha * 0.6;
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2 + t * 0.14;
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.52, a, a + 0.055 * Math.PI);
    ctx.stroke();
  }
  ctx.globalAlpha = alpha;

  // 중심 코어 — 어두운 원판 + 시안 글로우
  const core = ctx.createRadialGradient(0, 0, 0, 0, 0, R * 0.48);
  core.addColorStop(0,    'rgba(95,200,226,0.22)');
  core.addColorStop(0.55, 'rgba(10,30,48,0.55)');
  core.addColorStop(1,    'rgba(4,12,22,0.0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.48, 0, Math.PI * 2);
  ctx.fill();

  // 워드마크 — 너무 작으면(모바일 축소) 생략한다
  const fontPx = R * 0.145;
  if (fontPx >= 5.5) {
    const label = 'J.A.R.V.I.S.';
    ctx.font = `600 ${fontPx}px 'Space Grotesk', system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    const track = fontPx * 0.20;  // 자간
    const widths = [...label].map((ch) => ctx.measureText(ch).width);
    const total = widths.reduce((a, b) => a + b, 0) + track * (label.length - 1);
    let x = -total / 2;
    ctx.fillStyle = THEME.cyanBright;
    ctx.shadowColor = THEME.cyan;
    ctx.shadowBlur = fontPx * 0.9;
    for (let i = 0; i < label.length; i++) {
      ctx.fillText(label[i], x, 0);
      x += widths[i] + track;
    }
    ctx.shadowBlur = 0;
  }

  ctx.restore();
}

// ── Draw loop ─────────────────────────────────────────────────────────────────
function draw(ts) {
  // 유휴 ↔ 활동 크로스페이드 (약 0.4s)
  const logoTarget = hudState === 'idle' ? 1 : 0;
  logoMix += (logoTarget - logoMix) * 0.10;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (logoMix > 0.01) drawLogo(ts, Math.min(1, logoMix));
  if (logoMix < 0.99) drawSphere(ts, Math.min(1, 1 - logoMix));

  requestAnimationFrame(draw);
}

// ── Sphere (활동 중 파티클 구체) ─────────────────────────────────────────────
function drawSphere(ts, alpha) {
  const w  = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h / 2;

  ctx.save();
  ctx.globalAlpha = alpha;
  // 등장할 때 살짝 작게 들어온다(로고에서 넘어오는 전환감).
  const s = 0.94 + alpha * 0.06;
  ctx.translate(cx, cy);
  ctx.scale(s, s);
  ctx.translate(-cx, -cy);

  // smooth level
  level += (targetLevel - level) * 0.12;

  const baseR  = Math.min(w, h) * 0.30;
  const pulsed = baseR * (1 + level * 0.12 + Math.sin(ts * 0.002) * 0.004);

  // state-driven wave amplitude & rotation speed
  const waveAmp = hudState === 'thinking'    ? 0.52
                : hudState === 'tool_running' ? 0.42
                : hudState === 'error'        ? 0.25
                : hudState === 'listening'    ? 0.20
                : hudState === 'speaking'     ? 0.38
                : 0.32;
  const rotSpd  = hudState === 'thinking'    ? 0.005
                : hudState === 'tool_running' ? 0.004
                : hudState === 'speaking'     ? 0.006
                : 0.0022;
  const tSec    = ts / 1000;

  rotY += rotSpd + level * 0.005;
  const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
  const cosX = Math.cos(rotX), sinX = Math.sin(rotX);

  // Project all points
  const projected = [];
  for (const p of POINTS) {
    const wave = getWave(p.x, p.y, p.z, tSec);

    // Base deformation
    let r = pulsed * (1 + waveAmp * wave);

    // Scatter: high-wave points get an extra outward push (spray effect)
    if (wave > 0.5) {
      const scatter = (wave - 0.5) * 2.0 * p.jitter;
      r *= (1 + scatter * 0.55);
    }

    const rx = p.x * r, ry = p.y * r, rz = p.z * r;

    // 3-D rotation
    let q = rotateY({ x: rx, y: ry, z: rz }, cosY, sinY);
    q     = rotateX(q, cosX, sinX);

    const depth = (q.z / pulsed + 1.6) / 3.2;  // 0=back … 1=front
    const col   = waveColor(wave);

    // Size: bigger at front + at wave peaks
    const size = (0.5 + depth * 1.6 + Math.max(0, wave) * 1.8) * DPR;

    projected.push({ sx: cx + q.x, sy: cy - q.y, z: q.z, depth, col, size, wave });
  }

  // Painter's algorithm
  projected.sort((a, b) => a.z - b.z);

  // ── Pass 1: all dots (no shadow) ───────────────────────────────────────────
  ctx.shadowBlur = 0;
  for (const p of projected) {
    if (p.depth < 0.02) continue;
    const alpha = (0.12 + p.depth * 0.78).toFixed(2);
    ctx.beginPath();
    ctx.arc(p.sx, p.sy, p.size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${p.col.r},${p.col.g},${p.col.b},${alpha})`;
    ctx.fill();
  }

  // ── Pass 2: glow for front + spray peaks ───────────────────────────────────
  for (const p of projected) {
    const isSpray = p.wave > 0.55 && p.depth > 0.35;
    const isFront = p.depth > 0.80;
    if (!isSpray && !isFront) continue;

    const alpha = (0.12 + p.depth * 0.78).toFixed(2);
    ctx.shadowColor = `rgb(${p.col.r},${p.col.g},${p.col.b})`;
    ctx.shadowBlur  = (isSpray ? 10 : 6) * DPR;
    ctx.beginPath();
    ctx.arc(p.sx, p.sy, p.size, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${p.col.r},${p.col.g},${p.col.b},${alpha})`;
    ctx.fill();
  }
  ctx.shadowBlur = 0;

  // ── Core glow ──────────────────────────────────────────────────────────────
  if (level > 0.05) {
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, pulsed * 0.5);
    grad.addColorStop(0, `rgba(95,200,226,${(level * 0.2).toFixed(2)})`);
    grad.addColorStop(1, 'rgba(95,200,226,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  }

  ctx.restore();
}

requestAnimationFrame(draw);

// ── Public API ────────────────────────────────────────────────────────────────
window.HUD = { setState(s) { hudState = s; } };
