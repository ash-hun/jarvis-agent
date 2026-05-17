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

// ── State ─────────────────────────────────────────────────────────────────────
let hudState    = 'idle';
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

// ── Draw loop ─────────────────────────────────────────────────────────────────
function draw(ts) {
  const w  = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h / 2;
  ctx.clearRect(0, 0, w, h);

  // smooth level
  level += (targetLevel - level) * 0.12;

  const baseR  = Math.min(w, h) * 0.30;
  const pulsed = baseR * (1 + level * 0.12 + Math.sin(ts * 0.002) * 0.004);

  // state-driven wave amplitude & rotation speed
  const waveAmp = hudState === 'thinking'    ? 0.52
                : hudState === 'tool_running' ? 0.42
                : hudState === 'error'        ? 0.25
                : 0.32;
  const rotSpd  = hudState === 'thinking'    ? 0.005
                : hudState === 'tool_running' ? 0.004
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

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// ── Sphere click → voice toggle ───────────────────────────────────────────────
document.getElementById('sphere-hit').addEventListener('click', () => {
  if (window.voiceManager) window.voiceManager.toggle();
});

// ── Public API ────────────────────────────────────────────────────────────────
window.HUD = { setState(s) { hudState = s; } };
