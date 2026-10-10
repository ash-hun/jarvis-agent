// 에이전트 이름·명언. /brand.js(서버 설정)에서 오고, 못 받으면 기본값으로 뜬다.
const BRAND = window.BRAND || {};

export const AGENT_NAME = BRAND.name || 'J.A.R.V.I.S.';
export const QUOTE = BRAND.quote || '';

document.querySelectorAll('[data-brand="name"]').forEach((el) => { el.textContent = AGENT_NAME; });
document.title = `${AGENT_NAME} · HUD`;
