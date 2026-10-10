// 세션 — 목록, 전환·분기·생성, 웹소켓 연결과 재연결, 접속 직후 화면 채우기.
import { apiFetch, getToken, askForToken } from './api.js';
import { openSocket } from './ws.js';
import { escapeHtml } from './markdown.js';
import { setStatus, logActivity } from './shell.js';
import { appendMsg, appendHistory, resetMessages } from './messages.js';
import { setModel, resetUsage } from './usage.js';
import { hideArtifact } from './artifact.js';
import { setInputEnabled, setSlashCommands } from './composer.js';
import { fetchAgenda } from './agenda.js';
import { fetchTools } from './tools.js';
import { voice } from './voice-ui.js';
import { handleMessage, resetAgentStack } from './events.js';

const $list         = document.getElementById('session-list');
const $count        = document.getElementById('session-count');
const $idLabel      = document.getElementById('session-id-label');
const $sysModel     = document.getElementById('sys-model');
const $connBanner   = document.getElementById('connection-banner');

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 10000;
const WS_UNAUTHORIZED = 4401;  // 서버가 키 불일치로 끊을 때 쓰는 close code

let _currentSessionId = 'default';
let _reconnectDelay = RECONNECT_MIN_MS;

function renderSessions(sessions) {
  $list.innerHTML = '';
  $count.textContent = String(sessions.length).padStart(2, '0');
  for (const sid of sessions) {
    const isActive = sid === _currentSessionId;
    const div = document.createElement('div');
    div.className = `session${isActive ? ' active' : ''}`;
    div.innerHTML = `
      <span class="marker"></span>
      <span class="title">${escapeHtml(sid)}</span>
      <span class="meta">${isActive ? 'NOW' : ''}</span>
      ${isActive ? '<button class="fork-btn" title="Fork session">⑂</button>' : ''}`;
    div.querySelector('.title')?.addEventListener('click', () => { if (!isActive) connect(sid); });
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

document.getElementById('new-session-btn').addEventListener('click', async () => {
  const res = await apiFetch('/api/sessions', { method: 'POST' });
  const { session_id } = await res.json();
  connect(session_id);
});

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
  resetMessages();
  resetAgentStack();
  setInputEnabled(false);
  resetUsage();
  hideArtifact();
}

// 서버의 첫 메시지 — 세션·모델·도구·슬래시 명령을 받아 화면을 채운다.
function onConnected(msg) {
  const sid = msg.session_id || '—';
  const model = msg.model || '—';
  setModel(model);
  $idLabel.textContent = sid;
  $sysModel.textContent = model;
  $sysModel.title = model;
  logActivity(`session ${sid} linked`, 'ok');
  fetchAgenda();
  fetchTools();
  if (msg.sessions) renderSessions(msg.sessions);
  if (msg.slash_commands) setSlashCommands(msg.slash_commands);
  if (msg.voice && msg.voice.stt_mode) voice.setSttMode(msg.voice.stt_mode);
  setStatus('READY');
  setInputEnabled(true);
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
