// CONVERSATION 카드의 메시지 DOM — 일반 메시지, 💭, 스트리밍 응답, 도구 흔적, 대기 자리표시, 히스토리.
import { AGENT_NAME } from './brand.js';
import { escapeHtml, renderMarkdown, attachCopyBtns } from './markdown.js';
import { showLive, lastLine, CAPTION_HOLD_MS } from './shell.js';
import { extractArtifact, showArtifact } from './artifact.js';

const $messages = document.getElementById('messages');
const $msgCount = document.getElementById('msg-count');

let _msgCount = 0;
let _streamDiv = null;
let _streamText = '';
let _lastStreamText = '';  // voice TTS용 마지막 완성 텍스트
let _awaitDiv = null;      // 전송 직후 ~ 첫 agent_start 사이의 thinking 자리표시
const _toolMsgs = new Map(); // tool_call_id → { div, name }

function incMsgCount() {
  _msgCount++;
  $msgCount.textContent = _msgCount;
}

export function scrollToEnd() { $messages.scrollTop = $messages.scrollHeight; }

export function resetMessages() {
  $messages.innerHTML = '';
  _msgCount = 0;
  $msgCount.textContent = '0';
  _streamDiv = null;
  _streamText = '';
  _awaitDiv = null;
  _toolMsgs.clear();
}

export function typingDots() {
  return '<span class="typing-dots"><span></span><span></span><span></span></span>';
}

export function appendMsg(roleLabel, kind, bodyHtml = '') {
  const div = document.createElement('div');
  div.className = `msg ${kind}`;
  div.innerHTML = `<div class="role">${roleLabel}</div><div class="body"></div>`;
  div.querySelector('.body').innerHTML = bodyHtml;
  $messages.appendChild(div);
  scrollToEnd();
  incMsgCount();
  return div;
}

// 💭 는 길어서 기본으로 접는다. 한 줄 요약(decision · 확신도)을 클릭하면 해석 전문이 아래로 펼쳐진다.
export function appendThought(interp, decision, conf) {
  const div = appendMsg('💭', 'thought',
    `<div class="thought-head"><span class="chev">▸</span>` +
    `<span class="thought-meta">${escapeHtml(decision)} · ${conf}%</span></div>` +
    `<div class="thought-detail">${escapeHtml(interp)}</div>`);
  div.querySelector('.thought-head').addEventListener('click', () => div.classList.toggle('open'));
  return div;
}

function agentShell(extraClass = '') {
  const div = document.createElement('div');
  div.className = `msg agent ${extraClass}`.trim();
  div.innerHTML = '<div class="role"><span class="indicator">▌</span><span></span></div><div class="body"><div class="agent-text"></div></div>';
  div.querySelector('.role span:last-child').textContent = AGENT_NAME;
  return div;
}

// ── 스트리밍 응답 ─────────────────────────────────────────────────────────────
export function streamStart() {
  _streamText = '';
  const div = agentShell();
  div.querySelector('.agent-text').innerHTML = typingDots();
  $messages.appendChild(div);
  scrollToEnd();
  incMsgCount();
  _streamDiv = div;
}

export function streamDelta(delta) {
  if (!_streamDiv) streamStart();
  _streamText += delta;
  _streamDiv.querySelector('.agent-text').textContent = _streamText;
  scrollToEnd();
  const line = lastLine(_streamText);
  if (line) showLive(line);
}

export function streamEnd() {
  if (_streamDiv) {
    const textEl = _streamDiv.querySelector('.agent-text');
    if (!_streamText) {
      textEl.textContent = '';
    } else {
      textEl.innerHTML = renderMarkdown(_streamText);
      attachCopyBtns(textEl);
    }
  }
  _lastStreamText = _streamText;
  _streamDiv  = null;
  _streamText = '';
  const line = lastLine(_lastStreamText);
  if (line) showLive(line, CAPTION_HOLD_MS);

  if (_lastStreamText) {
    const artifact = extractArtifact(_lastStreamText);
    if (artifact) showArtifact(artifact.lang, artifact.code);
  }
}

export function lastStreamText() { return _lastStreamText; }

// ── 도구 흔적 — 스트리밍 메시지 안에 실행 중인 도구를 표시 ────────────────────
export function startToolTrace(toolCallId, name, cmd) {
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
  scrollToEnd();
  _toolMsgs.set(toolCallId, { div: traceDiv, name });
}

// 끝난 도구의 이름을 돌려준다. 모르는 id 면 null.
export function endToolTrace(toolCallId, ok) {
  const entry = _toolMsgs.get(toolCallId);
  if (!entry) return null;
  entry.div.className = `tool-trace ${ok ? 'done' : 'error'}`;
  entry.div.querySelector('.tool-icon').textContent   = ok ? '✓' : '✗';
  entry.div.querySelector('.tool-status').textContent = ok ? 'Done' : 'Error';
  _toolMsgs.delete(toolCallId);
  return entry.name;
}

// ── 대기 자리표시 — 첫 agent_start 가 오면 스트림 메시지로 바뀐다 ────────────
export function showAwaitPlaceholder() {
  hideAwaitPlaceholder();
  const div = agentShell('await');
  div.querySelector('.body').innerHTML = `${typingDots()}<span class="await-label">thinking</span>`;
  $messages.appendChild(div);
  scrollToEnd();
  _awaitDiv = div;
}

export function hideAwaitPlaceholder() {
  if (_awaitDiv) { _awaitDiv.remove(); _awaitDiv = null; }
}

// ── 세션 히스토리 — 스트림 종료 때와 같은 렌더 ───────────────────────────────
export function appendHistory(messages) {
  for (const msg of messages) {
    if (msg.role === 'user') {
      appendMsg('USER', 'user', escapeHtml(msg.text || ''));
    } else if (msg.role === 'assistant' && msg.text) {
      const div = agentShell();
      const textEl = div.querySelector('.agent-text');
      textEl.innerHTML = renderMarkdown(msg.text);
      attachCopyBtns(textEl);
      $messages.appendChild(div);
      incMsgCount();
    }
  }
  scrollToEnd();
}
