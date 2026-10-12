// ── Particle sphere (three.js) ────────────────────────────────────────────────
// 엠블럼 원판 안, 워드마크 뒤에 깔리는 입자 구. 점들이 구 표면에 나선형으로 고르게
// 놓이고, 점마다 셰이더에서 그린 후광으로 번진다(후처리 bloom 은 GPU 에 따라 화면이 하얗게
// 타는 문제가 있어 쓰지 않는다). 색은 지금 세션 에이전트의 primary 하나다.
// 에이전트 상태(window.HUD.state)에 따라 회전 속도·선명도·번짐·표면 물결이 달라진다.
// 링·중앙 어둡게 처리·워드마크는 이 위 레이어(hud.js 2D 캔버스, DOM)가 그린다.
// WebGL 이나 모듈 로드가 실패하면 원판은 CSS 배경(어두운 원)으로만 남는다.

import * as THREE from 'three';

const canvas = document.getElementById('sphere-gl');
const PALETTE = Object.assign(
  { primary: '#5fc8e2', accent: '#f0b35f' },
  (window.BRAND && window.BRAND.palette) || {},
);
const REDUCED_MOTION =
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const COLOR = {
  primary: new THREE.Color(PALETTE.primary),
  accent:  new THREE.Color(PALETTE.accent),
  red:     new THREE.Color('#f05f5f'),
};
// 원판 바탕 — styles.css .sphere-gl 배경과 같은 톤(primary 에 검정 86%).
// CSS 와 같게 보이도록 선형 공간이 아니라 sRGB 값에서 섞는다(선형에서 섞으면 출력 때 밝게 뜬다).
function discOf(hex) {
  const n = parseInt(hex.slice(1), 16);
  const k = 1 - 0.86;
  return new THREE.Color().setRGB(
    (((n >> 16) & 255) / 255) * k, (((n >> 8) & 255) / 255) * k, ((n & 255) / 255) * k,
    THREE.SRGBColorSpace,
  );
}
const DISC = discOf(PALETTE.primary);

// ── 상태별 목표값 ─────────────────────────────────────────────────────────────
// rot: 회전(rad/s) · bright: 밝기 · size: 점 크기 · bloom: 후광(번짐) 세기 · wave: 표면 물결
// tilt: 기울기 흔들림 · breathe: 반지름 맥동(진폭, Hz) · tint: 섞을 색과 비율
const STATES = {
  idle:         { rot: 0.10, bright: 0.55, size: 1.5, bloom: 0.45, wave: 0.0, tilt: 0.05, breathe: [0.00, 0.0], tint: ['primary', 0] },
  listening:    { rot: 0.16, bright: 0.85, size: 1.7, bloom: 0.75, wave: 0.1, tilt: 0.05, breathe: [0.035, 1.6], tint: ['primary', 0] },
  thinking:     { rot: 0.95, bright: 1.15, size: 2.0, bloom: 1.45, wave: 1.0, tilt: 0.35, breathe: [0.01, 0.8], tint: ['primary', 0] },
  tool_running: { rot: 0.55, bright: 1.0,  size: 1.9, bloom: 1.1,  wave: 0.5, tilt: 0.2,  breathe: [0.04, 2.0], tint: ['accent', 0.35] },
  speaking:     { rot: 0.30, bright: 0.95, size: 1.8, bloom: 0.9,  wave: 0.3, tilt: 0.1,  breathe: [0.00, 0.0], tint: ['primary', 0] },
  error:        { rot: 0.02, bright: 0.6,  size: 1.6, bloom: 0.6,  wave: 0.0, tilt: 0.0,  breathe: [0.00, 0.0], tint: ['red', 0.8] },
};

// ── Renderer / scene ──────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'low-power' });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
renderer.setClearColor(DISC, 1);

// 세션 에이전트가 바뀌면 app/brand.js 가 새 팔레트를 알린다
window.addEventListener('jarvis:palette', (e) => {
  const p = e.detail || {};
  if (p.primary) {
    COLOR.primary.set(p.primary);
    DISC.copy(discOf(p.primary));
    renderer.setClearColor(DISC, 1);
  }
  if (p.accent) COLOR.accent.set(p.accent);
});

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
camera.position.z = 4.2;  // 반지름 1 구가 원판의 약 3/4 을 채운다

// ── 입자: 구 표면 나선 배치 (phi = acos(-1 + 2i/N), theta = √(Nπ)·phi) ──────
const COUNT = 6000;
const positions = new Float32Array(COUNT * 3);
const seeds = new Float32Array(COUNT);
for (let i = 0; i < COUNT; i++) {
  const phi = Math.acos(-1 + (2 * i) / COUNT);
  const theta = Math.sqrt(COUNT * Math.PI) * phi;
  positions[i * 3]     = Math.cos(theta) * Math.sin(phi);
  positions[i * 3 + 1] = Math.sin(theta) * Math.sin(phi);
  positions[i * 3 + 2] = Math.cos(phi);
  seeds[i] = Math.random();
}
const geometry = new THREE.BufferGeometry();
geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));

const uniforms = {
  uTime:       { value: 0 },
  uColor:      { value: COLOR.primary.clone() },
  uBright:     { value: 0.55 },
  uGlow:       { value: 0.45 },
  uSize:       { value: 1.5 },
  uWave:       { value: 0 },
  uPulse:      { value: 1 },
  uPixelRatio: { value: renderer.getPixelRatio() },
};

const material = new THREE.ShaderMaterial({
  uniforms,
  transparent: true,
  depthWrite: false,
  blending: THREE.AdditiveBlending,
  vertexShader: /* glsl */ `
    attribute float aSeed;
    uniform float uTime, uSize, uWave, uPulse, uPixelRatio;
    varying float vFront;
    varying float vSpark;
    void main() {
      vec3 p = position;
      // 표면 물결 — 두 방향 사인을 곱해 흐르는 결을 만든다
      float w = sin(dot(p, vec3(4.1, 3.3, 5.2)) * 2.0 + uTime * 3.0) * sin(p.y * 6.0 - uTime * 2.0);
      p *= uPulse * (1.0 + uWave * 0.07 * w);
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_Position = projectionMatrix * mv;
      // 카메라(4.2)에서 앞면 3.2 ~ 뒷면 5.2 — 앞쪽일수록 1
      vFront = clamp((5.2 + mv.z) / 2.0, 0.0, 1.0);
      // 극소수 점만 반짝인다
      vSpark = step(0.985, aSeed) * (0.5 + 0.5 * sin(uTime * 4.0 + aSeed * 100.0));
      // 후광까지 담도록 점 크기의 4배 사각형을 그린다(핵은 가운데 1/4)
      gl_PointSize = 4.0 * uSize * uPixelRatio * (4.2 / -mv.z) * (1.0 + vSpark);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform vec3 uColor;
    uniform float uBright, uGlow;
    varying float vFront;
    varying float vSpark;
    void main() {
      float d = length(gl_PointCoord - 0.5);
      if (d > 0.5) discard;
      // 선명한 핵 + 가우시안 후광. uGlow 가 클수록 번지고, 작을수록 또렷하다.
      float core = smoothstep(0.14, 0.06, d);
      float halo = exp(-d * d * 30.0) * 0.28 * uGlow;
      float depth = 0.15 + 0.85 * vFront;
      vec3 col = mix(uColor, vec3(1.0), vSpark * 0.6 + core * 0.25);
      // 가산 합성이라 겹칠수록 밝아진다 — 점 하나는 어둡게 두어야 전체가 하얗게 타지 않는다
      gl_FragColor = vec4(col * uBright * depth, (core + halo) * depth);
    }
  `,
});

const group = new THREE.Group();
group.add(new THREE.Points(geometry, material));
group.rotation.x = 0.35;
scene.add(group);

function resize() {
  const w = Math.max(1, canvas.clientWidth);
  const h = Math.max(1, canvas.clientHeight);
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas);
resize();

// ── Loop ──────────────────────────────────────────────────────────────────────
const cur = { rot: 0.1, bright: 0.55, size: 1.5, bloom: 0.45, wave: 0, tilt: 0.05, amp: 0, hz: 0, tint: 0 };
const tintColor = new THREE.Color();
let spin = 0;
let last = performance.now();

function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  const t = now / 1000;
  const state = (window.HUD && window.HUD.state) || 'idle';
  const level = (window.HUD && window.HUD.level) || 0;
  const target = STATES[state] || STATES.idle;

  // 목표값으로 부드럽게 수렴 (약 0.3초)
  const k = Math.min(1, dt * 3.5);
  cur.rot    += ((REDUCED_MOTION ? 0 : target.rot) - cur.rot) * k;
  cur.bright += (target.bright - cur.bright) * k;
  cur.size   += (target.size - cur.size) * k;
  cur.bloom  += (target.bloom - cur.bloom) * k;
  cur.wave   += ((REDUCED_MOTION ? 0 : target.wave) - cur.wave) * k;
  cur.tilt   += (target.tilt - cur.tilt) * k;
  cur.amp    += ((REDUCED_MOTION ? 0 : target.breathe[0]) - cur.amp) * k;
  cur.hz     += (target.breathe[1] - cur.hz) * k;
  cur.tint   += (target.tint[1] - cur.tint) * k;
  // 섞을 색은 새 틴트가 생길 때만 바꾼다 — 틴트가 빠지는 동안 색이 튀지 않게
  if (target.tint[1] > 0) tintColor.copy(COLOR[target.tint[0]]);

  spin += cur.rot * dt;
  group.rotation.y = spin;
  group.rotation.x = 0.35 + Math.sin(t * 0.7) * cur.tilt;

  // 반지름: 상태별 맥동 + 말하는 중엔 발화 세기(level)를 따라 진동
  let pulse = 1 + cur.amp * Math.sin(t * Math.PI * 2 * cur.hz);
  if (state === 'speaking') pulse += level * 0.07;
  // 오류는 깜빡인다
  const flicker = state === 'error' ? 0.75 + 0.25 * Math.sin(t * 17) * Math.sin(t * 5.3) : 1;

  uniforms.uTime.value   = REDUCED_MOTION ? 0 : t;
  uniforms.uBright.value = cur.bright * flicker * (1 + level * 0.25);
  uniforms.uSize.value   = cur.size;
  uniforms.uWave.value   = cur.wave;
  uniforms.uPulse.value  = pulse;
  uniforms.uColor.value.copy(COLOR.primary).lerp(tintColor, cur.tint);
  uniforms.uGlow.value   = cur.bloom;

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
