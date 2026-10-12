// 에이전트 이름, 명언, 색. 첫 페인트는 /brand.js(main 설정)로 하고, 세션에 붙으면 그 세션 에이전트의 것으로 바꾼다.
// 이름과 명언은 live binding 이라 가져다 쓰는 모듈이 바뀐 값을 바로 본다.
const BRAND = window.BRAND || {};

export let AGENT_NAME = BRAND.name || 'J.A.R.V.I.S.';
export let QUOTE = BRAND.quote || '';
export let AGENT_ID = 'main';

function paintName() {
  document.querySelectorAll('[data-brand="name"]').forEach((el) => { el.textContent = AGENT_NAME; });
  document.title = `${AGENT_NAME} · HUD`;
}

// 세션 에이전트로 화면 정체성을 바꾼다. 바뀌었으면 true. 색은 CSS 변수와 'jarvis:palette' 이벤트(hud.js, sphere.js)로 간다
export function applyBrand(agent) {
  if (!agent || agent.id === AGENT_ID) return false;
  AGENT_ID = agent.id;
  AGENT_NAME = agent.name || AGENT_NAME;
  QUOTE = agent.quote || '';
  const p = agent.palette || {};
  const s = document.documentElement.style;
  if (p.primary) s.setProperty('--primary', p.primary);
  if (p.accent) s.setProperty('--accent', p.accent);
  if (p.background) s.setProperty('--bg-0', p.background);
  (p.nebula || []).forEach((c, i) => s.setProperty(`--nebula-${i}`, c));
  document.documentElement.dataset.agent = agent.id;
  paintName();
  window.dispatchEvent(new CustomEvent('jarvis:palette', { detail: p }));
  return true;
}

paintName();
