// SYSTEM 카드의 도구 목록.
import { apiFetch } from './api.js';

const $toggle = document.getElementById('tools-toggle');
const $list   = document.getElementById('tools-list');
const $count  = document.getElementById('tools-count');

// 에이전트마다 쓰는 도구가 달라 지금 세션 기준으로 받는다. session.js 가 접속 때 정한다
let _sessionId = '';
export function setToolsSession(sessionId) { _sessionId = sessionId; }

export async function fetchTools() {
  try {
    const qs = _sessionId ? `?session_id=${encodeURIComponent(_sessionId)}` : '';
    const res = await apiFetch(`/api/tools${qs}`);
    if (!res.ok) return;
    const { tools } = await res.json();
    $count.textContent = tools.length;
    $list.innerHTML = '';
    for (const t of tools) {
      const li = document.createElement('li');
      li.innerHTML = '<span class="lock"></span><span class="nm"></span><span class="ds"></span>';
      li.querySelector('.lock').textContent = t.approval ? '🔒' : '·';
      li.querySelector('.nm').textContent = t.name;
      li.querySelector('.ds').textContent = t.description;
      li.title = `${t.name}${t.approval ? ' (실행 전 승인 필요)' : ''}\n${t.description}`;
      $list.appendChild(li);
    }
  } catch (e) {
    console.warn('tools fetch failed:', e);
  }
}

$toggle.addEventListener('click', () => {
  const open = $toggle.getAttribute('aria-expanded') !== 'true';
  $toggle.setAttribute('aria-expanded', String(open));
  $list.hidden = !open;
});
