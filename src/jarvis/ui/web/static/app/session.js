// 세션 — 목록, 전환·분기·생성, 웹소켓 연결과 재연결, 접속 직후 화면 채우기.
import { apiFetch, getToken, askForToken } from './api.js';
import { openSocket } from './ws.js';
import { escapeHtml } from './markdown.js';
import { setStatus, logActivity, showQuote } from './shell.js';
import { appendMsg, appendHistory, resetMessages } from './messages.js';
import { resetFocus } from './focus.js';
import { setModel, resetUsage } from './usage.js';
import { hideArtifact } from './artifact.js';
import { setInputEnabled, setSlashCommands } from './composer.js';
import { fetchAgenda } from './agenda.js';
import { fetchTools, setToolsSession } from './tools.js';
import { voice, cue } from './voice-ui.js';
import { setPhrases } from './phrases.js';
import { setWakeEnabled } from './wake.js';
import { handleMessage, resetAgentStack, resetBackgroundThought } from './events.js';
import { setReplyClassifier } from './reply.js';
import { applyBrand, AGENT_ID } from './brand.js';
import { loadAgents, agents, agentById, isTeam, setActiveAgents } from './agents.js';

const $list         = document.getElementById('session-list');
const $count        = document.getElementById('session-count');
const $idLabel      = document.getElementById('session-id-label');
const $sysModel     = document.getElementById('sys-model');
const $connBanner   = document.getElementById('connection-banner');
const $agentSwitch  = document.getElementById('agent-switch');

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 10000;
const WS_UNAUTHORIZED = 4401;  // 서버가 키 불일치로 끊을 때 쓰는 close code

let _currentSessionId = 'default';
let _reconnectDelay = RECONNECT_MIN_MS;
// 세션 id → 에이전트 id. connected 와 /api/sessions 가 채운다
let _sessionAgents = {};

function renderSessions(sessions, sessionAgents) {
  if (sessionAgents) _sessionAgents = sessionAgents;
  $list.innerHTML = '';
  $count.textContent = String(sessions.length).padStart(2, '0');
  for (const sid of sessions) {
    const isActive = sid === _currentSessionId;
    const div = document.createElement('div');
    div.className = `session${isActive ? ' active' : ''}`;
    // 세션 앞 표식은 그 세션 에이전트의 색
    const agent = agentById(_sessionAgents[sid] || 'main');
    if (agent && isTeam()) {
      div.style.setProperty('--agent-color', agent.palette.primary);
      div.dataset.agent = agent.id;
      div.title = agent.name;
    }
    div.innerHTML = `
      <span class="marker"></span>
      <span class="title">${escapeHtml(sid)}</span>
      <span class="meta">${isActive ? 'NOW' : ''}</span>
      ${isActive ? '<button class="fork-btn" title="Fork session">⑂</button>'
                 : '<button class="fork-btn delete-btn" title="세션 삭제">✕</button>'}`;
    div.querySelector('.title')?.addEventListener('click', () => { if (!isActive) connect(sid); });
    // 보고 있는 세션은 못 지운다. 지우려면 다른 세션으로 옮긴 뒤.
    div.querySelector('.delete-btn')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(`세션 "${sid}" 과 그 대화를 지웁니다. 되돌릴 수 없습니다.`)) return;
      const res = await apiFetch(`/api/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' });
      if (!res.ok) { logActivity(`세션 삭제 실패 · ${sid} · ${res.status}`, 'err'); return; }
      logActivity(`세션 삭제 · ${sid}`);
      const body = await (await apiFetch('/api/sessions')).json();
      renderSessions(body.sessions, body.agents);
    });
    if (isActive) {
      div.querySelector('.fork-btn')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const res = await apiFetch(`/api/sessions/${encodeURIComponent(sid)}/branch`, { method: 'POST' });
        const { session_id } = await res.json();
        connect(session_id);
      });
    }
    $list.appendChild(div);
  }
}

// 에이전트끼리 대화하면 서버에 대화 세션(peer-…)이 새로 생긴다. 일하는 에이전트가 바뀔 때 목록을 다시 받는다
window.addEventListener('jarvis:activity', async () => {
  try {
    const res = await apiFetch('/api/sessions');
    if (!res.ok) return;
    const body = await res.json();
    renderSessions(body.sessions, body.agents);
  } catch { /* 목록은 다음 접속 때 맞춰진다 */ }
});

// 새 세션은 지금 보고 있는 에이전트의 것
async function createSession(agentId) {
  const res = await apiFetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent: agentId }),
  });
  if (!res.ok) { logActivity(`세션 생성 실패 · ${agentId} · ${res.status}`, 'err'); return null; }
  return (await res.json()).session_id;
}

document.getElementById('new-session-btn').addEventListener('click', async () => {
  const sid = await createSession(AGENT_ID);
  if (sid) connect(sid);
});

// 에이전트끼리의 대화 세션(peer-부른쪽-받는쪽). 사용자가 직접 말을 거는 세션이 아니다
const PEER_PREFIX = 'peer-';

// 에이전트 전환: 그 에이전트의 열린 세션(대화 세션 제외)이 있으면 가장 위의 것으로, 없으면 새로 만든다
async function switchAgent(agentId) {
  if (agentId === AGENT_ID) return;
  const sid = Object.keys(_sessionAgents)
    .find((s) => _sessionAgents[s] === agentId && !s.startsWith(PEER_PREFIX)) || await createSession(agentId);
  if (sid) connect(sid);
}

function renderAgentSwitch() {
  $agentSwitch.hidden = !isTeam();
  $agentSwitch.innerHTML = '';
  for (const a of agents()) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `agent-chip${a.id === AGENT_ID ? ' active' : ''}`;
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', String(a.id === AGENT_ID));
    b.style.setProperty('--agent-color', a.palette.primary);
    b.dataset.agent = a.id;
    b.textContent = a.name;
    b.title = a.description || a.name;
    b.addEventListener('click', () => switchAgent(a.id));
    $agentSwitch.appendChild(b);
  }
}

async function fetchAndRenderHistory(sessionId) {
  try {
    const res = await apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (!res.ok) return;
    if (_currentSessionId !== sessionId) return;  // 받는 사이 세션이 바뀌었으면 버린다
    const { messages } = await res.json();
    if (_currentSessionId !== sessionId) return;
    if (messages && messages.length) appendHistory(messages);
  } catch (e) {
    console.error('history fetch failed:', e);
  }
}

function resetChatUI() {
  resetFocus();
  resetMessages();
  resetAgentStack();
  setInputEnabled(false);
  resetUsage();
  hideArtifact();
}

let _connectedOnce = false;  // 첫 접속의 에이전트는 전환이 아니다

// 서버의 첫 메시지 — 세션·모델·도구·슬래시 명령을 받아 화면을 채운다.
async function onConnected(msg) {
  await loadAgents();
  if (msg.voice) setPhrases(msg.voice.phrases);
  // 세션 에이전트의 이름과 색으로 화면을 바꾼다. 바뀌었으면 명언도 그 에이전트 것으로
  if (applyBrand(msg.agent)) {
    showQuote();
    if (_connectedOnce) cue(`persona_${msg.agent.main ? 'jarvis' : msg.agent.id}`);
  }
  _connectedOnce = true;
  renderAgentSwitch();
  setActiveAgents(msg.active_agents || []);
  const sid = msg.session_id || '—';
  const model = msg.model || '—';
  setModel(model);
  $idLabel.textContent = sid;
  $sysModel.textContent = model;
  $sysModel.title = model;
  logActivity(`session ${sid} linked`, 'ok');
  fetchAgenda();
  setToolsSession(msg.session_id);
  fetchTools();
  if (msg.sessions) renderSessions(msg.sessions, msg.session_agents);
  if (msg.slash_commands) setSlashCommands(msg.slash_commands);
  if (msg.voice && msg.voice.stt_mode) voice.setSttMode(msg.voice.stt_mode);
  setWakeEnabled(!!(msg.voice && msg.voice.wake));
  setReplyClassifier(msg.reply_classifier);
  setStatus('READY');
  setInputEnabled(true);
  // 다른 세션(또는 끊기기 전)의 사고가 끝났는지는 알 수 없다
  resetBackgroundThought();
  HUD.setState('idle');
}

export function connect(sessionId = _currentSessionId) {
  _currentSessionId = sessionId;
  resetChatUI();
  fetchAndRenderHistory(sessionId).then(() => {
    if (_currentSessionId === sessionId) {
      appendMsg('SYS', 'sys', `— SESSION · ${new Date().toLocaleTimeString('ko-KR', { hour12: false })} · ${escapeHtml(sessionId)} —`);
    }
  });

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const tokenQs = getToken() ? `&token=${encodeURIComponent(getToken())}` : '';
  openSocket(`${proto}://${location.host}/ws?session_id=${encodeURIComponent(sessionId)}${tokenQs}`, {
    onOpen() {
      $connBanner.classList.add('hidden');
      _reconnectDelay = RECONNECT_MIN_MS;
    },
    onClose(ev) {
      setInputEnabled(false);
      if (ev.code === WS_UNAUTHORIZED) {
        // 키 불일치 — 재시도 루프 대신 키를 묻고 바로 다시 연결한다
        if (askForToken()) connect(_currentSessionId);
        else { $connBanner.classList.remove('hidden'); logActivity('접근 키 없음', 'err'); }
        return;
      }
      $connBanner.classList.remove('hidden');
      logActivity('link lost — retrying', 'err');
      setTimeout(() => connect(_currentSessionId), _reconnectDelay);
      _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX_MS);
    },
    onMessage(msg) {
      if (msg.type === 'connected') onConnected(msg);
      else handleMessage(msg);
    },
  });
}
