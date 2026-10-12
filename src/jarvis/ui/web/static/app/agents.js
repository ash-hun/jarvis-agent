// 최상위 에이전트 목록(/api/agents). AGENDA 라벨, 세션 목록 표시, 에이전트 전환이 같이 쓴다.
import { apiFetch } from './api.js';

let _agents = [];
let _loading = null;

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
