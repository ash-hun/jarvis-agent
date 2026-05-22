'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $messages       = document.getElementById('messages');
const $input          = document.getElementById('chat-input');
const $sendBtn        = document.getElementById('send-btn');
const $clock          = document.getElementById('clock');
const $statusText     = document.getElementById('status-text');
const $statusTick     = document.getElementById('status-tick');
const $statusPill     = document.getElementById('status-pill');
const $sessionTitle   = document.getElementById('session-title');
const $sessionIdLabel = document.getElementById('session-id-label');
const $msgCount       = document.getElementById('msg-count');
const $ftMsg          = document.getElementById('ft-msg');
const $ftUptime       = document.getElementById('ft-uptime');
const $ftModel        = document.getElementById('ft-model');
const $sbModel        = document.getElementById('sb-model');
const $connBanner     = document.getElementById('connection-banner');

const $approvalOverlay = document.getElementById('approval-overlay');
const $approvalReason  = document.getElementById('approval-reason');
const $approvalCommand = document.getElementById('approval-command');
const $btnAllow        = document.getElementById('btn-allow');
const $btnDeny         = document.getElementById('btn-deny');

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  const d   = new Date();
  const pad = n => String(n).padStart(2, '0');
  $clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

// ── Uptime ────────────────────────────────────────────────────────────────────
const _startTime = Date.now();
function updateUptime() {
  const s   = Math.floor((Date.now() - _startTime) / 1000);
  const pad = n => String(n).padStart(2, '0');
  $ftUptime.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}
setInterval(updateUptime, 1000);
updateUptime();

// ── Status pill ───────────────────────────────────────────────────────────────
function setStatus(label, cls = '') {
  $statusText.textContent = label;
  $statusPill.className   = 'status-pill' + (cls ? ' ' + cls : '');
}

// ── Message counter ───────────────────────────────────────────────────────────
let _msgCount = 0;
function incMsgCount() {
  _msgCount++;
  $msgCount.textContent = _msgCount;
  $ftMsg.textContent    = _msgCount;
}

// ── Message helpers ───────────────────────────────────────────────────────────
function appendMsg(roleLabel, kind, bodyHtml = '') {
  const div = document.createElement('div');
  div.className = `msg ${kind}`;
  div.innerHTML = `<div class="role">${roleLabel}</div><div class="body"></div>`;
  div.querySelector('.body').innerHTML = bodyHtml;
  $messages.appendChild(div);
  $messages.scrollTop = $messages.scrollHeight;
  incMsgCount();
  return div;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function typingDots() {
  return '<span class="typing-dots"><span></span><span></span><span></span></span>';
}

// ── Streaming assistant message ───────────────────────────────────────────────
let _streamDiv  = null;
let _streamText = '';

function streamStart() {
  _streamText = '';
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.innerHTML = '<div class="role"><span class="indicator">▌</span><span>JARVIS</span></div><div class="body"><div class="agent-text"></div></div>';
  div.querySelector('.agent-text').innerHTML = typingDots();
  $messages.appendChild(div);
  $messages.scrollTop = $messages.scrollHeight;
  incMsgCount();
  _streamDiv = div;
}

function streamDelta(delta) {
  if (!_streamDiv) streamStart();
  _streamText += delta;
  _streamDiv.querySelector('.agent-text').textContent = _streamText;
  $messages.scrollTop = $messages.scrollHeight;
}

function streamEnd() {
  if (_streamDiv) {
    const textEl = _streamDiv.querySelector('.agent-text');
    if (!_streamText) textEl.textContent = '';
  }
  _streamDiv  = null;
  _streamText = '';
}

// ── Tool message tracking ─────────────────────────────────────────────────────
const _toolMsgs = new Map(); // tool_call_id → div

// ── Approval ──────────────────────────────────────────────────────────────────
let _currentApprovalId = null;

function showApproval(id, command, reason) {
  _currentApprovalId         = id;
  $approvalReason.textContent  = reason || '도구 실행 승인이 필요합니다.';
  $approvalCommand.textContent = command;
  $approvalOverlay.classList.remove('hidden');
}

function hideApproval() {
  $approvalOverlay.classList.add('hidden');
  _currentApprovalId = null;
}

$btnAllow.addEventListener('click', () => { if (_currentApprovalId) sendApproval(_currentApprovalId, true); });
$btnDeny.addEventListener('click',  () => { if (_currentApprovalId) sendApproval(_currentApprovalId, false); });

// ── Session management ────────────────────────────────────────────────────────
let _currentSessionId = 'default';

function renderSessions(sessions) {
  const list = document.getElementById('session-list');
  list.innerHTML = '';
  document.getElementById('session-count').textContent = String(sessions.length).padStart(2, '0');
  for (const sid of sessions) {
    const isActive = sid === _currentSessionId;
    const div = document.createElement('div');
    div.className = `session${isActive ? ' active' : ''}`;
    div.innerHTML = `
      <span class="marker"></span>
      <span class="title">${escapeHtml(sid)}</span>
      <span class="meta">${isActive ? 'NOW' : ''}</span>
      ${isActive ? '<button class="fork-btn" title="Fork session">⑂</button>' : ''}`;
    div.querySelector('.title')?.addEventListener('click', () => {
      if (!isActive) connect(sid);
    });
    if (isActive) {
      div.querySelector('.fork-btn')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/branch`, { method: 'POST' });
        const { session_id } = await res.json();
        connect(session_id);
      });
    }
    list.appendChild(div);
  }
}

document.getElementById('new-session-btn').addEventListener('click', async () => {
  const res = await fetch('/api/sessions', { method: 'POST' });
  const { session_id } = await res.json();
  connect(session_id);
});

// ── Session history ───────────────────────────────────────────────────────────
async function fetchAndRenderHistory(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (!res.ok) return;
    // Guard: if session switched while fetching, discard stale results
    if (_currentSessionId !== sessionId) return;
    const { messages } = await res.json();
    if (_currentSessionId !== sessionId) return;
    if (!messages || messages.length === 0) return;
    for (const msg of messages) {
      if (msg.role === 'user') {
        appendMsg('USER', 'user', escapeHtml(msg.text || ''));
      } else if (msg.role === 'assistant' && msg.text) {
        const div = document.createElement('div');
        div.className = 'msg agent';
        div.innerHTML =
          '<div class="role"><span class="indicator">▌</span><span>JARVIS</span></div>' +
          '<div class="body"><div class="agent-text"></div></div>';
        div.querySelector('.agent-text').textContent = msg.text;
        $messages.appendChild(div);
        incMsgCount();
      }
    }
    $messages.scrollTop = $messages.scrollHeight;
  } catch (e) {
    console.error('history fetch failed:', e);
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws              = null;
let _reconnectDelay = 1000;
let _intentionalClose = false;

function resetChatUI() {
  $messages.innerHTML = '';
  _msgCount = 0;
  $msgCount.textContent = '0';
  $ftMsg.textContent    = '0';
  _streamDiv  = null;
  _streamText = '';
  _toolMsgs.clear();
  setInputEnabled(false);
}

function connect(sessionId = _currentSessionId) {
  if (ws) {
    _intentionalClose = true;
    ws.close();
    ws = null;
  }
  _currentSessionId = sessionId;
  resetChatUI();
  fetchAndRenderHistory(sessionId).then(() => {
    if (_currentSessionId === sessionId) {
      appendMsg('SYS', 'sys', `— SESSION · ${new Date().toLocaleTimeString('ko-KR', {hour12: false})} · ${escapeHtml(sessionId)} —`);
    }
  });

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws?session_id=${encodeURIComponent(sessionId)}`);

  ws.addEventListener('open', () => {
    $connBanner.classList.add('hidden');
    _reconnectDelay = 1000;
  });

  ws.addEventListener('close', () => {
    if (_intentionalClose) { _intentionalClose = false; return; }
    ws = null;
    setInputEnabled(false);
    $connBanner.classList.remove('hidden');
    setTimeout(() => connect(_currentSessionId), _reconnectDelay);
    _reconnectDelay = Math.min(_reconnectDelay * 2, 10000);
  });

  ws.addEventListener('error', () => ws?.close());

  ws.addEventListener('message', (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    handleMessage(msg);
  });
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function sendApproval(id, approved) {
  send({ type: 'approval_response', id, approved });
  hideApproval();
}

// ── Message router ────────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {

    case 'connected': {
      const sid = msg.session_id || '—';
      const model = msg.model || '—';
      $sessionTitle.textContent   = sid;
      $sessionIdLabel.textContent = sid;
      if ($ftModel) $ftModel.textContent = model;
      if ($sbModel) $sbModel.textContent = model;
      if (msg.sessions) renderSessions(msg.sessions);
      setStatus('READY');
      setInputEnabled(true);
      HUD.setState('idle');
      break;
    }

    case 'agent_start':
      setStatus('THINKING', 'thinking');
      HUD.setState('thinking');
      streamStart();
      break;

    case 'message_update':
      if (msg.text_delta) streamDelta(msg.text_delta);
      break;

    case 'stream_delta':
      streamDelta(msg.text);
      break;

    case 'agent_end':
      streamEnd();
      setStatus('READY');
      HUD.setState('idle');
      setInputEnabled(true);
      break;

    case 'tool_execution_start': {
      const name = msg.tool_name || 'tool';
      const args = msg.args || {};
      const cmd  = args.command || args.query || (Object.keys(args).length ? JSON.stringify(args) : '');

      if (!_streamDiv) streamStart();
      _streamDiv.querySelector('.agent-text').innerHTML = typingDots();

      const traceDiv = document.createElement('div');
      traceDiv.className = 'tool-trace running';
      traceDiv.innerHTML =
        `<span class="tool-icon">⚡</span>` +
        `<span class="tool-name">${escapeHtml(name)}</span>` +
        (cmd ? `<span class="tool-cmd">${escapeHtml(cmd)}</span>` : '') +
        `<span class="tool-status">running…</span>`;

      const body = _streamDiv.querySelector('.body');
      body.insertBefore(traceDiv, body.querySelector('.agent-text'));
      $messages.scrollTop = $messages.scrollHeight;

      _toolMsgs.set(msg.tool_call_id, { div: traceDiv, name });
      setStatus('EXECUTING', 'executing');
      HUD.setState('tool_running');
      break;
    }

    case 'tool_execution_end': {
      const entry = _toolMsgs.get(msg.tool_call_id);
      if (entry) {
        const ok = !msg.is_error;
        entry.div.className = `tool-trace ${ok ? 'done' : 'error'}`;
        entry.div.querySelector('.tool-icon').textContent   = ok ? '✓' : '✗';
        entry.div.querySelector('.tool-status').textContent = ok ? 'Done' : 'Error';
        _toolMsgs.delete(msg.tool_call_id);
      }
      setStatus('THINKING', 'thinking');
      HUD.setState('thinking');
      break;
    }

    case 'agent_error':
      streamEnd();
      appendMsg('SYS', 'err', escapeHtml(msg.message || 'Unknown error'));
      setStatus('ERROR', 'error');
      HUD.setState('error');
      setInputEnabled(true);
      setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, 3000);
      break;

    case 'error':
      appendMsg('SYS', 'err', escapeHtml(msg.message || 'Error'));
      setStatus('ERROR', 'error');
      HUD.setState('error');
      setInputEnabled(true);
      setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, 3000);
      break;

    case 'approval_request':
      showApproval(msg.id, msg.command, msg.reason);
      break;
  }
}

// ── Input handling ────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  $input.disabled   = !enabled;
  $sendBtn.disabled = !enabled;
  if (enabled) $input.focus();
}

function submitMessage() {
  const text = $input.value.trim();
  if (!text) return;
  appendMsg('USER', 'user', escapeHtml(text));
  $input.value = '';
  setInputEnabled(false);
  send({ type: 'user_message', text });
}

document.getElementById('composer').addEventListener('submit', (e) => {
  e.preventDefault();
  submitMessage();
});

// Ctrl+K → abort  /  Enter → approval accept
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'k') {
    e.preventDefault();
    send({ type: 'abort' });
    streamEnd();
    setStatus('READY');
    HUD.setState('idle');
    setInputEnabled(true);
  }
  if (e.key === 'Enter' && !$approvalOverlay.classList.contains('hidden')) {
    e.preventDefault();
    if (_currentApprovalId) sendApproval(_currentApprovalId, true);
  }
});

// ── Voice ─────────────────────────────────────────────────────────────────────
const voice = new VoiceManager((transcript) => {
  $input.value = transcript;
  submitMessage();
});
window.voiceManager = voice;


// ── Sidebar collapse ──────────────────────────────────────────────────────────
const SB_KEY = 'jarvis.sbCollapsed';
if (localStorage.getItem(SB_KEY) === '1') document.body.classList.add('sb-collapsed');
document.getElementById('collapse-btn').addEventListener('click', () => {
  const next = !document.body.classList.contains('sb-collapsed');
  document.body.classList.toggle('sb-collapsed', next);
  localStorage.setItem(SB_KEY, next ? '1' : '0');
});

// ── Boot ──────────────────────────────────────────────────────────────────────
setInputEnabled(false);
connect('default');
