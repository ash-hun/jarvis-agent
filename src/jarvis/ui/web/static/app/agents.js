// 최상위 에이전트 목록(/api/agents). AGENDA 라벨, 세션 목록 표시, 에이전트 전환이 같이 쓴다.
import { apiFetch } from './api.js';
import { AGENT_ID } from './brand.js';
import { logActivity } from './shell.js';

let _agents = [];
let _loading = null;
// 지금 일하는 에이전트 id(서버 agent_activity). 둘 이상이면 구체가 그 색들을 섞는다
let _active = [];

export function loadAgents() {
  // 정의는 서버 기동 때 정해지므로 한 번만 받는다. 실패하면 다음 호출에서 다시 받는다
  if (!_loading) {
    _loading = apiFetch('/api/agents')
      .then((res) => (res.ok ? res.json() : { agents: [] }))
      .then((body) => { _agents = body.agents || []; return _agents; })
      .catch(() => { _loading = null; return _agents; });
  }
  return _loading;
}

export function agents() { return _agents; }

export function agentById(id) {
  return _agents.find((a) => a.id === id) || null;
}

// 에이전트가 하나뿐이면 라벨을 달 이유가 없다
export function isTeam() { return _agents.length > 1; }

// 에이전트 이름 라벨. 색은 그 에이전트의 primary 를 CSS 변수로 넘긴다
export function agentTag(id) {
  const a = agentById(id);
  const span = document.createElement('span');
  span.className = 'agent-tag';
  span.textContent = a ? a.name : (id || 'main');
  if (a) span.style.setProperty('--agent-color', a.palette.primary);
  span.title = a && a.description ? a.description : span.textContent;
  return span;
}

// 함께 일하는 에이전트의 색. 지금 보고 있는 에이전트가 끼어 있으면 그 색이 먼저다. 둘 미만이면 빈 목록
export function blendColors(active, currentId) {
  if (active.length < 2) return [];
  const ordered = active.includes(currentId) ? [currentId, ...active.filter((id) => id !== currentId)] : active;
  return ordered.map((id) => agentById(id)?.palette.primary).filter(Boolean);
}

// 서버가 알려 준 활동을 칩 표시와 구체(sphere.js 의 'jarvis:activity')에 반영한다. 세션 에이전트가 바뀌어도 다시 부른다
export function setActiveAgents(active = _active) {
  const wasTeam = _active.length > 1;
  _active = active || [];
  document.querySelectorAll('.agent-chip').forEach((b) => b.classList.toggle('busy', _active.includes(b.dataset.agent)));
  const colors = blendColors(_active, AGENT_ID);
  window.dispatchEvent(new CustomEvent('jarvis:activity', { detail: { active: _active, colors } }));
  if (_active.length > 1 && !wasTeam) {
    logActivity(`⇄ ${_active.map((id) => agentById(id)?.name || id).join(' · ')} 함께 작업 중`, 'proactive');
  }
}
