'use strict';

// ── Color palette ────────────────────────────────────────────────────────────
const C = {
  primary:   '#00d4ff',
  secondary: '#00ffcc',
  accent:    '#7fffef',
  warn:      '#ff8800',
  error:     '#ff4466',
  bg:        '#05090f',
  dim:       '#4a7a8a',
};

// ── Ring definitions ─────────────────────────────────────────────────────────
const RINGS = [
  { r: 190, speed:  0.20, dash: [25, 12], color: 'primary',   width: 1.5 },
  { r: 160, speed: -0.40, dash: [8,  20], color: 'secondary', width: 1.0 },
  { r: 130, speed:  0.70, dash: [40,  8], color: 'primary',   width: 2.0 },
  { r: 100, speed: -1.10, dash: [5,  15], color: 'accent',    width: 1.5 },
  { r:  70, speed:  1.80, dash: [15,  5], color: 'secondary', width: 1.0 },
];

// ── HUD state ────────────────────────────────────────────────────────────────
let hudState = 'idle'; // 'idle' | 'thinking' | 'tool_running' | 'error'

function setHudState(s) { hudState = s; }

// ── Canvas setup ─────────────────────────────────────────────────────────────
const canvas = document.getElementById('hud-canvas');
const ctx    = canvas.getContext('2d');

function resize() {
  const panel = canvas.parentElement;
  const size  = Math.min(panel.clientWidth, panel.clientHeight - 120);
  canvas.width  = size;
  canvas.height = size;
}
window.addEventListener('resize', resize);
resize();

// ── Hex grid ─────────────────────────────────────────────────────────────────
function drawHexGrid(cx, cy, t) {
  const step   = 28;
  const cols   = Math.ceil(canvas.width  / step) + 2;
  const rows   = Math.ceil(canvas.height / step) + 2;
  const ox     = -step;
  const oy     = -step;
  const pulse  = 0.03 + 0.015 * Math.sin(t * 0.4);

  ctx.save();
  ctx.strokeStyle = `rgba(0,212,255,${pulse})`;
  ctx.lineWidth   = 0.5;

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = ox + col * step + (row % 2 === 0 ? 0 : step / 2);
      const y = oy + row * step * 0.866;
      hexPath(x, y, step * 0.48);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function hexPath(x, y, r) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    const px = x + r * Math.cos(a);
    const py = y + r * Math.sin(a);
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.closePath();
}

// ── Rings ────────────────────────────────────────────────────────────────────
function drawRings(cx, cy, t) {
  const speedMul = hudState === 'thinking'    ? 2.2
                 : hudState === 'tool_running' ? 1.6
                 : hudState === 'error'        ? 0.5
                 : 1.0;

  const alpha = hudState === 'thinking' ? 0.95 : 0.75;

  RINGS.forEach(ring => {
    const angle = t * ring.speed * speedMul;
    const color = C[ring.color];

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);

    ctx.beginPath();
    ctx.arc(0, 0, ring.r, 0, Math.PI * 2);
    ctx.setLineDash(ring.dash);
    ctx.lineDashOffset = 0;
    ctx.strokeStyle = hexAlpha(color, alpha);
    ctx.lineWidth   = ring.width;
    ctx.shadowColor = color;
    ctx.shadowBlur  = hudState === 'thinking' ? 16 : 8;
    ctx.stroke();

    ctx.restore();
  });
}

// ── Core (Arc Reactor) ───────────────────────────────────────────────────────
function drawCore(cx, cy, t) {
  // Outer glow ring
  const glowR  = 48;
  const pulse  = Math.sin(t * (hudState === 'thinking' ? 4 : 2)) * 0.5 + 0.5;
  const coreC  = hudState === 'error'        ? C.error
               : hudState === 'tool_running' ? C.warn
               : C.primary;

  const grad = ctx.createRadialGradient(cx, cy, 4, cx, cy, glowR);
  grad.addColorStop(0,   hexAlpha(coreC, 0.9));
  grad.addColorStop(0.4, hexAlpha(coreC, 0.3 + pulse * 0.15));
  grad.addColorStop(1,   hexAlpha(coreC, 0));

  ctx.beginPath();
  ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
  ctx.fillStyle = grad;
  ctx.fill();

  // Inner ring
  ctx.beginPath();
  ctx.arc(cx, cy, 22, 0, Math.PI * 2);
  ctx.strokeStyle = hexAlpha(coreC, 0.9);
  ctx.lineWidth   = 2;
  ctx.shadowColor = coreC;
  ctx.shadowBlur  = 18;
  ctx.stroke();

  // Center dot
  ctx.beginPath();
  ctx.arc(cx, cy, 7, 0, Math.PI * 2);
  ctx.fillStyle = coreC;
  ctx.shadowColor = coreC;
  ctx.shadowBlur  = 24;
  ctx.fill();
  ctx.shadowBlur  = 0;

  // State label
  const label = hudState === 'thinking'    ? 'PROCESSING'
              : hudState === 'tool_running' ? 'EXECUTING'
              : hudState === 'error'        ? 'ERROR'
              : 'STANDBY';
  ctx.font         = 'bold 10px "Courier New", monospace';
  ctx.fillStyle    = hexAlpha(coreC, 0.8);
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, cx, cy + 42);
}

// ── Error shake effect ────────────────────────────────────────────────────────
let _errorShakeT = 0;
function maybeShake(cx, cy) {
  if (hudState !== 'error') { _errorShakeT = 0; return { x: cx, y: cy }; }
  _errorShakeT += 0.25;
  const amp = Math.max(0, 4 - _errorShakeT * 0.4);
  return {
    x: cx + Math.sin(_errorShakeT * 17) * amp,
    y: cy + Math.cos(_errorShakeT * 13) * amp,
  };
}

// ── Main loop ────────────────────────────────────────────────────────────────
let _t = 0;
let _last = null;

function animate(ts) {
  if (_last !== null) _t += (ts - _last) / 1000;
  _last = ts;

  const W  = canvas.width;
  const H  = canvas.height;
  const cx = W / 2;
  const cy = H / 2;

  ctx.clearRect(0, 0, W, H);
  ctx.save();

  const { x, y } = maybeShake(cx, cy);
  ctx.translate(x - cx, y - cy);

  drawHexGrid(cx, cy, _t);
  drawRings(cx, cy, _t);
  drawCore(cx, cy, _t);

  ctx.restore();
  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);

// ── Utility ───────────────────────────────────────────────────────────────────
function hexAlpha(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── Public API ────────────────────────────────────────────────────────────────
window.HUD = { setState: setHudState };
