'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $messages       = document.getElementById('messages');
const $input          = document.getElementById('chat-input');
const $sendBtn        = document.getElementById('send-btn');
const $micBtn         = document.getElementById('mic-btn');
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
  _streamDiv  = appendMsg('AGENT', 'agent', typingDots());
}

function streamDelta(delta) {
  if (!_streamDiv) streamStart();
  _streamText += delta;
  _streamDiv.querySelector('.body').textContent = _streamText;
  $messages.scrollTop = $messages.scrollHeight;
}

function streamEnd() {
  if (_streamDiv && !_streamText) {
    _streamDiv.querySelector('.body').textContent = '';
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

// ── WebSocket ─────────────────────────────────────────────────────────────────
let ws             = null;
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
    setTimeout(connect, _reconnectDelay);
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
      $sessionTitle.textContent   = sid;
      $sessionIdLabel.textContent = sid;
      setStatus('READY');
      setInputEnabled(true);
      HUD.setState('idle');
      appendMsg('SYS', 'sys', `— SESSION INITIALIZED · ${new Date().toLocaleTimeString('ko-KR', {hour12: false})} · session: ${escapeHtml(sid)} —`);
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
      const div  = appendMsg('SYS', 'sys', `⚡ running ${escapeHtml(name)}…`);
      _toolMsgs.set(msg.tool_call_id, { div, name });
      setStatus('EXECUTING', 'executing');
      HUD.setState('tool_running');
      break;
    }

    case 'tool_execution_end': {
      const entry = _toolMsgs.get(msg.tool_call_id);
      if (entry) {
        const icon = msg.is_error ? '✗' : '✓';
        entry.div.querySelector('.body').textContent = `${icon} ${entry.name} [${msg.is_error ? 'error' : 'done'}]`;
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
window.voiceManager = voice;

$micBtn.addEventListener('click', () => {
  if (!voice.supported) { $micBtn.title = '이 브라우저는 음성 입력을 지원하지 않습니다'; return; }
  const active = voice.toggle();
  $micBtn.classList.toggle('listening', voice.listening);
});

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
connect();
