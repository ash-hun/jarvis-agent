'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $history    = document.getElementById('chat-history');
const $input      = document.getElementById('chat-input');
const $sendBtn    = document.getElementById('send-btn');
const $micBtn     = document.getElementById('mic-btn');
const $clock      = document.getElementById('clock');
const $sessionId  = document.getElementById('session-id');
const $statusBadge = document.getElementById('status-badge');
const $toolOverlay = document.getElementById('tool-overlay');
const $connBanner  = document.getElementById('connection-banner');

const $approvalOverlay = document.getElementById('approval-overlay');
const $approvalReason  = document.getElementById('approval-reason');
const $approvalCommand = document.getElementById('approval-command');
const $btnAllow        = document.getElementById('btn-allow');
const $btnDeny         = document.getElementById('btn-deny');

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  $clock.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

// ── Status badge ──────────────────────────────────────────────────────────────
function setStatus(label, cls = '') {
  $statusBadge.textContent = label;
  $statusBadge.className   = 'status-badge' + (cls ? ' ' + cls : '');
}

// ── Chat history helpers ──────────────────────────────────────────────────────
function appendMsg(role, html, extra = '') {
  const div = document.createElement('div');
  div.className = `msg ${role} ${extra}`.trim();

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'YOU' : role === 'assistant' ? 'JARVIS' : '';

  const body = document.createElement('div');
  body.className = 'msg-body';
  body.innerHTML = html;

  if (label.textContent) div.appendChild(label);
  div.appendChild(body);
  $history.appendChild(div);
  $history.scrollTop = $history.scrollHeight;
  return div;
}

function appendTool(name, state = 'running') {
  const div = document.createElement('div');
  div.className = `msg tool ${state === 'done' ? 'done' : state === 'error' ? 'error-msg' : ''}`;

  const dot = document.createElement('span');
  dot.className = 'tool-icon';
  dot.textContent = state === 'done' ? '✓' : state === 'error' ? '✗' : '⚡';

  div.appendChild(dot);
  div.appendChild(document.createTextNode(` ${name}`));
  $history.appendChild(div);
  $history.scrollTop = $history.scrollHeight;
  return div;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Tool overlay (canvas panel) ───────────────────────────────────────────────
const _overlayItems = new Map(); // tool_call_id → element

function overlayAdd(id, name) {
  const item = document.createElement('div');
  item.className = 'tool-item';
  item.innerHTML = `<span class="tool-dot"></span><span>${escapeHtml(name)}</span>`;
  $toolOverlay.appendChild(item);
  _overlayItems.set(id, item);
}

function overlayDone(id, isError) {
  const item = _overlayItems.get(id);
  if (!item) return;
  item.classList.add(isError ? 'error' : 'done');
  setTimeout(() => { item.remove(); _overlayItems.delete(id); }, 2000);
}

// ── Streaming assistant message ───────────────────────────────────────────────
let _streamDiv  = null;
let _streamText = '';

function streamStart() {
  _streamText = '';
  _streamDiv  = appendMsg('assistant', '', 'streaming');
}

function streamDelta(delta) {
  if (!_streamDiv) streamStart();
  _streamText += delta;
  _streamDiv.querySelector('.msg-body').textContent = _streamText;
  $history.scrollTop = $history.scrollHeight;
}

function streamEnd() {
  if (_streamDiv) {
    _streamDiv.classList.remove('streaming');
    _streamDiv = null;
  }
  _streamText = '';
}

// ── Tool message tracking ─────────────────────────────────────────────────────
const _toolMsgs = new Map(); // tool_call_id → { chatDiv, name }

// ── Pending approval ──────────────────────────────────────────────────────────
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

$btnAllow.addEventListener('click', () => {
  if (_currentApprovalId) sendApproval(_currentApprovalId, true);
});
$btnDeny.addEventListener('click', () => {
  if (_currentApprovalId) sendApproval(_currentApprovalId, false);
});

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws     = null;
let _reconnectTimer = null;
let _reconnectDelay = 1000;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.addEventListener('open', () => {
    $connBanner.classList.add('hidden');
    _reconnectDelay = 1000;
  });

  ws.addEventListener('close', () => {
    ws = null;
    setInputEnabled(false);
    $connBanner.classList.remove('hidden');
    _reconnectTimer = setTimeout(connect, _reconnectDelay);
    _reconnectDelay = Math.min(_reconnectDelay * 2, 10000);
  });

  ws.addEventListener('error', () => {
    ws?.close();
  });

  ws.addEventListener('message', (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    handleMessage(msg);
  });
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

function sendApproval(id, approved) {
  send({ type: 'approval_response', id, approved });
  hideApproval();
}

// ── Message router ────────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {
    case 'connected':
      $sessionId.textContent = `SESSION: ${msg.session_id || '—'}`;
      setStatus('READY');
      setInputEnabled(true);
      HUD.setState('idle');
      break;

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
      overlayAdd(msg.tool_call_id, name);
      const chatDiv = appendTool(name, 'running');
      _toolMsgs.set(msg.tool_call_id, { chatDiv, name });
      setStatus('EXECUTING', 'tool_running');
      HUD.setState('tool_running');
      break;
    }

    case 'tool_execution_end': {
      const entry = _toolMsgs.get(msg.tool_call_id);
      const isErr = !!msg.is_error;
      overlayDone(msg.tool_call_id, isErr);
      if (entry) {
        const dot = entry.chatDiv.querySelector('.tool-icon');
        if (dot) dot.textContent = isErr ? '✗' : '✓';
        entry.chatDiv.classList.toggle('done', !isErr);
        entry.chatDiv.classList.toggle('error-msg', isErr);
        _toolMsgs.delete(msg.tool_call_id);
      }
      setStatus('THINKING', 'thinking');
      HUD.setState('thinking');
      break;
    }

    case 'agent_error':
      streamEnd();
      appendMsg('assistant', escapeHtml(msg.message || 'Unknown error'), 'error-msg');
      setStatus('ERROR', 'error');
      HUD.setState('error');
      setInputEnabled(true);
      setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, 3000);
      break;

    case 'error':
      appendMsg('assistant', escapeHtml(msg.message || 'Error'), 'error-msg');
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
}

function submitMessage() {
  const text = $input.value.trim();
  if (!text) return;
  appendMsg('user', escapeHtml(text));
  $input.value = '';
  setInputEnabled(false);
  send({ type: 'user_message', text });
}

$sendBtn.addEventListener('click', submitMessage);
$input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitMessage();
  }
});

// Ctrl+K → abort
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'k') {
    e.preventDefault();
    send({ type: 'abort' });
    streamEnd();
    setStatus('READY');
    HUD.setState('idle');
    setInputEnabled(true);
  }
});

// ── Voice ─────────────────────────────────────────────────────────────────────
const voice = new VoiceManager((transcript) => {
  $input.value = transcript;
  submitMessage();
});

$micBtn.addEventListener('click', () => {
  if (!voice.supported) {
    $micBtn.title = '이 브라우저는 음성 입력을 지원하지 않습니다';
    return;
  }
  voice.toggle();
});

// ── Boot ──────────────────────────────────────────────────────────────────────
setInputEnabled(false);
connect();
