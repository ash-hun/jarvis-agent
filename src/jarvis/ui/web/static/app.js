'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $messages          = document.getElementById('messages');
const $input             = document.getElementById('chat-input');
const $sendBtn           = document.getElementById('send-btn');
const $slashPopup        = document.getElementById('slash-popup');
const $inputHighlight    = document.getElementById('input-highlight');
const $inputHighlightInner = document.getElementById('input-highlight-inner');
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
      if (msg.slash_commands) _slashCmds = msg.slash_commands;
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

// ── Slash command interaction ─────────────────────────────────────────────────
let _slashCmds     = [];  // [{name, description}, ...] — fetched from server
let _slashFiltered = [];  // currently shown subset
let _slashVisible  = false;
let _slashIdx      = -1;

const _CMD_HIGHLIGHT_RE = /(?<!\S)\/([a-zA-Z?][a-zA-Z0-9_-]*)/g;

function buildHighlightHtml(text) {
  let result = '';
  let lastIdx = 0;
  let m;
  _CMD_HIGHLIGHT_RE.lastIndex = 0;
  while ((m = _CMD_HIGHLIGHT_RE.exec(text)) !== null) {
    result += escapeHtml(text.slice(lastIdx, m.index));
    result += `<span class="slash-token">${escapeHtml(m[0])}</span>`;
    lastIdx = m.index + m[0].length;
  }
  result += escapeHtml(text.slice(lastIdx));
  return result;
}

function updateHighlight() {
  $inputHighlightInner.innerHTML = buildHighlightHtml($input.value);
  $inputHighlightInner.style.transform = `translateX(-${$input.scrollLeft}px)`;
}

function setSlashActive(idx) {
  _slashIdx = idx;
  $slashPopup.querySelectorAll('.slash-item').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });
}

function selectSlashItem(idx) {
  const cmd = _slashFiltered[idx];
  if (!cmd) return;
  $input.value = '/' + cmd.name + ' ';
  updateHighlight();
  hideSlashPopup();
  $input.focus();
}

function showSlashPopup(cmds) {
  _slashFiltered = cmds;
  $slashPopup.innerHTML =
    '<div class="slash-popup-head">SLASH COMMANDS</div>';

  cmds.forEach((cmd, i) => {
    const item = document.createElement('div');
    item.className = 'slash-item';
    item.setAttribute('role', 'option');
    item.innerHTML =
      `<span class="cmd-name">/${escapeHtml(cmd.name)}</span>` +
      `<span class="cmd-desc">${escapeHtml(cmd.description || '')}</span>`;

    item.addEventListener('mousedown', (e) => {
      e.preventDefault(); // keep input focus
      selectSlashItem(i);
    });
    item.addEventListener('mousemove', () => setSlashActive(i));
    $slashPopup.appendChild(item);
  });

  _slashVisible = true;
  $slashPopup.classList.remove('hidden');
  setSlashActive(0);
}

function hideSlashPopup() {
  _slashVisible = false;
  _slashIdx     = -1;
  _slashFiltered = [];
  $slashPopup.classList.add('hidden');
}

// Input event: update highlight + show/filter popup when typing /cmd
$input.addEventListener('input', () => {
  updateHighlight();
  const val   = $input.value;
  const match = val.match(/^\/([a-zA-Z0-9_?-]*)$/);
  if (match) {
    const q        = match[1].toLowerCase();
    const filtered = _slashCmds.filter(c => c.name.startsWith(q));
    if (filtered.length > 0) { showSlashPopup(filtered); return; }
  }
  hideSlashPopup();
});

// Scroll sync between input and highlight overlay
$input.addEventListener('scroll', updateHighlight);

// Keyboard navigation inside popup
$input.addEventListener('keydown', (e) => {
  if (!_slashVisible) return;
  const n = _slashFiltered.length;
  if (n === 0) return;

  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault();
      setSlashActive((_slashIdx + 1) % n);
      break;
    case 'ArrowUp':
      e.preventDefault();
      setSlashActive((_slashIdx - 1 + n) % n);
      break;
    case 'Tab':
    case 'Enter':
      e.preventDefault();
      selectSlashItem(_slashIdx);
      break;
    case 'Escape':
      e.preventDefault();
      hideSlashPopup();
      break;
  }
});

// Close popup on blur (mousedown on items uses preventDefault so blur won't fire for those)
$input.addEventListener('blur', () => {
  setTimeout(hideSlashPopup, 150);
});

// ── Input handling ────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  $input.disabled                = !enabled;
  $sendBtn.disabled              = !enabled;
  $inputHighlight.style.opacity  = enabled ? '1' : '0.4';
  if (enabled) $input.focus();
}

function submitMessage() {
  const text = $input.value.trim();
  if (!text) return;
  if (_slashVisible) return; // popup open — let keydown handle it
  appendMsg('USER', 'user', escapeHtml(text));
  $input.value = '';
  updateHighlight();
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
