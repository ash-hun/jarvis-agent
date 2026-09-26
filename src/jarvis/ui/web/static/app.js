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
const $sessionIdLabel = document.getElementById('session-id-label');
const $msgCount       = document.getElementById('msg-count');
const $uptime         = document.getElementById('uptime');
const $sysModel       = document.getElementById('sys-model');
const $connBanner     = document.getElementById('connection-banner');
const $caption        = document.getElementById('reactor-caption');
const $activityLog    = document.getElementById('activity-log');

const $approvalOverlay = document.getElementById('approval-overlay');
const $approvalReason  = document.getElementById('approval-reason');
const $approvalCommand = document.getElementById('approval-command');
const $btnAllow        = document.getElementById('btn-allow');
const $btnDeny         = document.getElementById('btn-deny');

// ── Usage Dashboard DOM refs ──────────────────────────────────────────────────
const $uIn            = document.getElementById('u-in');
const $uOut           = document.getElementById('u-out');
const $uCr            = document.getElementById('u-cr');
const $uCw            = document.getElementById('u-cw');
const $uCost          = document.getElementById('u-cost');
const $uTotalTokens   = document.getElementById('usage-total-tokens');
const $usageSparkline = document.getElementById('usage-sparkline');

// ── Artifact Panel DOM refs ───────────────────────────────────────────────────
const $artifactPanel    = document.getElementById('artifact-panel');
const $artifactLang     = document.getElementById('artifact-lang');
const $artifactCode     = document.getElementById('artifact-code');
const $artifactCopyBtn  = document.getElementById('artifact-copy-btn');
const $artifactCloseBtn = document.getElementById('artifact-close-btn');

// ── Brand ─────────────────────────────────────────────────────────────────────
// 에이전트 이름·명언은 /brand.js(서버 설정)에서 온다. 못 받으면 기본값으로 뜬다.
const BRAND      = window.BRAND || {};
const AGENT_NAME = BRAND.name  || 'J.A.R.V.I.S.';
const QUOTE      = BRAND.quote || '';
document.querySelectorAll('[data-brand="name"]').forEach((el) => { el.textContent = AGENT_NAME; });
document.title = `${AGENT_NAME} · HUD`;

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
  $uptime.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
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
}

// ── Reactor caption ───────────────────────────────────────────────────────────
// 쉴 때는 명언, 응답·proactive 메시지가 오면 그 한 줄. 잠시 뒤 명언으로 돌아간다.
const CAPTION_HOLD_MS = 20000;
let _captionTimer = null;

function setCaption(text, kind) {
  const swap = () => {
    $caption.className = `reactor-caption ${kind}`;
    $caption.textContent = text;
  };
  if ($caption.classList.contains(kind)) { swap(); return; }
  $caption.classList.add('fading');
  setTimeout(swap, 350);
}

function showQuote() {
  clearTimeout(_captionTimer);
  setCaption(QUOTE, 'quote');
}

function showLive(text, holdMs = 0) {
  clearTimeout(_captionTimer);
  setCaption(text, 'live');
  if (holdMs) _captionTimer = setTimeout(showQuote, holdMs);
}

// 마크다운 기호를 걷어낸 마지막 비어 있지 않은 줄
function lastLine(text) {
  const lines = text.split('\n').map((l) => l.replace(/[#*`>_]/g, '').trim()).filter(Boolean);
  const line = lines.length ? lines[lines.length - 1] : '';
  return line.length > 160 ? line.slice(0, 157) + '…' : line;
}

// ── Activity log ──────────────────────────────────────────────────────────────
const ACTIVITY_MAX = 60;

function logActivity(text, kind = '') {
  const d   = new Date();
  const pad = n => String(n).padStart(2, '0');
  const li  = document.createElement('li');
  if (kind) li.className = kind;
  li.innerHTML = `<time>${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}</time><span class="msg-text"></span>`;
  const span = li.querySelector('.msg-text');
  span.textContent = text;
  span.title = text;
  $activityLog.prepend(li);
  while ($activityLog.children.length > ACTIVITY_MAX) $activityLog.lastElementChild.remove();
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

// ── Markdown Renderer ─────────────────────────────────────────────────────────
// 외부 의존 없는 자체 구현 — h1-h3, p, ul/ol/li, pre/code, strong, em, hr
const _codeStore = {};  // uid → raw code text (copy 버튼용)

function inlineParse(text) {
  let s = escapeHtml(text);
  s = s.replace(/\*\*(.+?)\*\*/g,  '<strong>$1</strong>');
  s = s.replace(/__(.+?)__/g,       '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g,       '<em>$1</em>');
  s = s.replace(/`([^`]+)`/g,       '<code class="inline-code">$1</code>');
  return s;
}

function renderMarkdown(src) {
  const lines = src.split('\n');
  let out = '', i = 0, listType = null;

  const closeList = () => { if (listType) { out += `</${listType}>`; listType = null; } };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith('```')) {
      closeList();
      const lang = line.slice(3).trim() || 'text';
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++; }
      const rawCode = codeLines.join('\n');
      const uid = Math.random().toString(36).slice(2, 9);
      _codeStore[uid] = rawCode;
      out += `<div class="code-block">` +
        `<div class="code-head">` +
        `<span class="code-lang">${escapeHtml(lang)}</span>` +
        `<button class="copy-btn" data-uid="${uid}">COPY</button>` +
        `</div>` +
        `<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(rawCode)}</code></pre>` +
        `</div>`;
      i++; continue;
    }

    if (line.trim() === '')    { closeList(); out += '<br>'; i++; continue; }
    if (/^---+$/.test(line.trim())) { closeList(); out += '<hr>'; i++; continue; }

    const h3 = line.match(/^### (.+)/); if (h3) { closeList(); out += `<h3>${inlineParse(h3[1])}</h3>`; i++; continue; }
    const h2 = line.match(/^## (.+)/);  if (h2) { closeList(); out += `<h2>${inlineParse(h2[1])}</h2>`; i++; continue; }
    const h1 = line.match(/^# (.+)/);   if (h1) { closeList(); out += `<h1>${inlineParse(h1[1])}</h1>`; i++; continue; }

    const ul = line.match(/^[-*+] (.+)/);
    if (ul) { if (listType !== 'ul') { closeList(); out += '<ul>'; listType = 'ul'; } out += `<li>${inlineParse(ul[1])}</li>`; i++; continue; }

    const ol = line.match(/^\d+[.)]\s+(.+)/);
    if (ol) { if (listType !== 'ol') { closeList(); out += '<ol>'; listType = 'ol'; } out += `<li>${inlineParse(ol[1])}</li>`; i++; continue; }

    closeList();
    out += `<p>${inlineParse(line)}</p>`;
    i++;
  }
  closeList();
  return out;
}

function attachCopyBtns(container) {
  container.querySelectorAll('.copy-btn[data-uid]').forEach(btn => {
    btn.addEventListener('click', () => {
      const code = _codeStore[btn.dataset.uid] || '';
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = 'COPIED!';
        setTimeout(() => { btn.textContent = 'COPY'; }, 2000);
      }).catch(() => {
        const pre = btn.closest('.code-block')?.querySelector('pre');
        if (pre) {
          const r = document.createRange();
          r.selectNode(pre);
          window.getSelection().removeAllRanges();
          window.getSelection().addRange(r);
        }
      });
    });
  });
}

// ── Artifact ──────────────────────────────────────────────────────────────────
let _artifactRaw = '';

function extractArtifact(text) {
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let best = null, m;
  while ((m = re.exec(text)) !== null) {
    const lang = m[1] || 'text';
    const code = m[2];
    const lines = code.split('\n').filter(l => l.trim()).length;
    if (lines >= 8 && (!best || code.length > best.code.length)) best = { lang, code };
  }
  return best;
}

function showArtifact(lang, code) {
  _artifactRaw = code;
  $artifactLang.textContent = lang.toUpperCase() || 'CODE';
  $artifactCode.textContent = code;
  $artifactPanel.classList.add('open');
}

function hideArtifact() { $artifactPanel.classList.remove('open'); }

$artifactCloseBtn.addEventListener('click', hideArtifact);
$artifactCopyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(_artifactRaw).then(() => {
    $artifactCopyBtn.textContent = 'COPIED!';
    setTimeout(() => { $artifactCopyBtn.textContent = 'COPY'; }, 2000);
  });
});

// ── Usage Dashboard ───────────────────────────────────────────────────────────
let _currentModel = '—';
const _sessionUsage = { input: 0, output: 0, cache_read: 0, cache_write: 0, turns: [] };

function getCostRate(model) {
  const m = (model || '').toLowerCase();
  if (m.includes('opus'))       return { in: 15,    out: 75   };
  if (m.includes('sonnet'))     return { in: 3,     out: 15   };
  if (m.includes('haiku'))      return { in: 0.8,   out: 4    };
  if (m.includes('gpt-4o-mini')) return { in: 0.15,  out: 0.6  };
  if (m.includes('gpt-4o'))    return { in: 5,     out: 15   };
  if (m.includes('gemini'))    return { in: 1.25,  out: 5    };
  return { in: 3, out: 15 };
}

function fmtTok(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1)     + 'K';
  return String(n);
}

function updateUsage(usage) {
  _sessionUsage.input      += usage.input      || 0;
  _sessionUsage.output     += usage.output     || 0;
  _sessionUsage.cache_read  += usage.cache_read  || 0;
  _sessionUsage.cache_write += usage.cache_write || 0;
  _sessionUsage.turns.push({ in: usage.input || 0, out: usage.output || 0 });
  if (_sessionUsage.turns.length > 16) _sessionUsage.turns.shift();
  renderUsagePanel();
}

function renderUsagePanel() {
  const s = _sessionUsage;
  const total = s.input + s.output;
  $uIn.textContent          = fmtTok(s.input);
  $uOut.textContent         = fmtTok(s.output);
  $uCr.textContent          = fmtTok(s.cache_read);
  $uCw.textContent          = fmtTok(s.cache_write);
  $uTotalTokens.textContent = fmtTok(total);

  const rate = getCostRate(_currentModel);
  const cost = (s.input / 1e6) * rate.in + (s.output / 1e6) * rate.out;
  $uCost.textContent = '$' + cost.toFixed(4);

  // Sparkline
  const maxOut = Math.max(...s.turns.map(t => t.out), 1);
  $usageSparkline.innerHTML = s.turns.map(t => {
    const h = Math.max(4, Math.round((t.out / maxOut) * 32));
    return `<div class="spark-bar" style="height:${h}px" title="${t.out} output tokens"></div>`;
  }).join('');
}

function resetUsage() {
  _sessionUsage.input = _sessionUsage.output = _sessionUsage.cache_read = _sessionUsage.cache_write = 0;
  _sessionUsage.turns = [];
  renderUsagePanel();
}

// ── Agenda (스케줄 + open loops) ──────────────────────────────────────────────
// 서버에 변경 이벤트가 없으므로 접속·inner thought·응답 종료·조작 직후, 그리고 1분마다
// 다시 불러온다(다음 실행 시각이 흘러가므로).
const $scheduleList = document.getElementById('schedule-list');
const $openloopList = document.getElementById('openloop-list');
const $agendaCount  = document.getElementById('agenda-count');

// 오늘이면 HH:MM, 내일이면 '내일 HH:MM', 그 뒤면 'M/D HH:MM'. 24시간 안이면 남은 시간도.
function fmtWhen(iso) {
  const d = new Date(iso);
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const dayDiff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) -
                              new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  const day = dayDiff === 0 ? '' : dayDiff === 1 ? '내일 ' : `${d.getMonth() + 1}/${d.getDate()} `;
  const mins = Math.round((d - now) / 60000);
  const left = mins < 60 ? `${Math.max(mins, 0)}분 후` : mins < 1440 ? `${Math.round(mins / 60)}시간 후` : '';
  return `${day}${hm}${left ? ' · ' + left : ''}`;
}

function agendaItem(text, when, cls = '') {
  const li = document.createElement('li');
  li.className = `agenda-item ${cls}`.trim();
  li.innerHTML = '<div class="what"><span class="txt"></span><span class="when"></span></div><div class="acts"></div>';
  li.querySelector('.txt').textContent = text;
  li.querySelector('.what').title = text;
  li.querySelector('.when').textContent = when;
  return li;
}

function renderAgenda({ schedules = [], open_loops = [] }) {
  $scheduleList.innerHTML = '';
  for (const t of schedules) {
    let when = t.next_run ? fmtWhen(t.next_run) : (t.enabled ? '다음 실행 없음' : '꺼짐');
    if (t.run_until) {
      const u = new Date(t.run_until);
      when += ` · ~${u.getMonth() + 1}/${u.getDate()} ${String(u.getHours()).padStart(2, '0')}:${String(u.getMinutes()).padStart(2, '0')}`;
    }
    if (t.once) when += ` · 한 번 · ${t.kind === 'task' ? '작업' : '알림'}`;
    // /schedule 로 만든 작업의 description 은 자동 문구라, 사용자가 쓴 프롬프트를 보여준다
    const fromSlash = t.name.startsWith('slash-') || t.name.startsWith('once-');
    const label = fromSlash ? t.prompt : (t.description || t.prompt || t.name);
    const li = agendaItem(label, when, t.enabled ? '' : 'off');
    const sw = document.createElement('button');
    sw.type = 'button';
    sw.className = 'switch';
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', String(t.enabled));
    sw.setAttribute('aria-label', `${t.name} ${t.enabled ? '끄기' : '켜기'}`);
    sw.addEventListener('click', () => toggleSchedule(t.name, !t.enabled));
    li.querySelector('.acts').appendChild(sw);
    $scheduleList.appendChild(li);
  }

  $openloopList.innerHTML = '';
  for (const lp of open_loops) {
    const when = lp.due_ms ? `기한 ${fmtWhen(new Date(lp.due_ms).toISOString())}` : '';
    const li = agendaItem(lp.description, when);
    for (const [status, label, cls] of [['done', '✓', 'done'], ['dismissed', '✕', 'dismiss']]) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `icon-btn ${cls}`;
      b.textContent = label;
      b.title = status === 'done' ? '완료' : '무시';
      b.addEventListener('click', () => closeOpenLoop(lp, status, li));
      li.querySelector('.acts').appendChild(b);
    }
    $openloopList.appendChild(li);
  }

  const active = schedules.filter(t => t.enabled).length + open_loops.length;
  $agendaCount.textContent = String(active).padStart(2, '0');
}

async function fetchAgenda() {
  try {
    const res = await fetch('/api/agenda');
    if (res.ok) renderAgenda(await res.json());
  } catch (e) {
    console.warn('agenda fetch failed:', e);
  }
}

async function closeOpenLoop(loop, status, li) {
  li.classList.add('leaving');
  const res = await fetch(`/api/openloops/${encodeURIComponent(loop.id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).catch(() => null);
  if (res && res.ok) {
    logActivity(`${status === 'done' ? '✓ 완료' : '✕ 무시'} · ${loop.description}`, status === 'done' ? 'ok' : '');
  } else {
    logActivity(`open loop 처리 실패 · ${loop.description}`, 'err');
  }
  fetchAgenda();
}

async function toggleSchedule(name, enabled) {
  const res = await fetch(`/api/schedules/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }).catch(() => null);
  logActivity(res && res.ok ? `⏱ ${name} ${enabled ? '켜짐' : '꺼짐'}` : `스케줄 변경 실패 · ${name}`, res && res.ok ? '' : 'err');
  fetchAgenda();
}

setInterval(fetchAgenda, 60000);

// ── Schedule notices (스케줄 알림) ────────────────────────────────────────────
// 서버가 스케줄 실행 결과를 {type:'reminder'} 로 방송한다. 대화 🔔 · 캡션 · Activity ·
// 브라우저 시스템 알림(탭이 뒤에 있을 때) · 음성으로 알린다.
function noticeSuffix(n) {
  if (n.missed) return ' (놓친 알림)';
  if (n.delayed_sec > 60) return ` (지연 ${Math.round(n.delayed_sec / 60)}분)`;
  return '';
}

function showNotice(n) {
  const suffix = noticeSuffix(n);
  const text = (n.text || '').trim();
  // 작업이면 무엇을 실행한 결과인지 제목을 붙인다
  const header = n.kind === 'task' ? `<div class="notice-title">⏱ ${escapeHtml(n.title || '')}${escapeHtml(suffix)}</div>` : '';
  const body = n.kind === 'task'
    ? header + renderMarkdown(text)
    : `${escapeHtml(text)}${suffix ? `<span class="thought-meta">${escapeHtml(suffix)}</span>` : ''}`;
  const div = appendMsg('🔔', n.error ? 'err' : 'proactive', body);
  attachCopyBtns(div);

  logActivity(`🔔 ${n.kind === 'task' ? n.title : text}${suffix}`, n.error ? 'err' : 'proactive');
  showLive(lastLine(text) || n.title || '', CAPTION_HOLD_MS);

  if ('Notification' in window && Notification.permission === 'granted' &&
      (document.hidden || !document.hasFocus())) {
    try {
      new Notification(`${AGENT_NAME}${suffix}`, { body: text.slice(0, 240), tag: n.id });
    } catch (e) { /* 일부 브라우저는 페이지에서 직접 생성을 막는다 */ }
  }

  // 놓친 알림은 한꺼번에 몰려올 수 있어 읽지 않는다
  if (!n.missed && text) {
    voice.setProcessing();
    send({ type: 'voice_tts_request', text: text.slice(0, 400) });
  }
  fetchAgenda();  // 한 번 실행 알림은 울린 뒤 목록에서 빠진다
}

// 시스템 알림 권한은 사용자가 /schedule 을 쓸 때 묻는다(맥락 없는 권한 요청을 피한다)
function askNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

// ── Tools (system card) ───────────────────────────────────────────────────────
const $toolsToggle = document.getElementById('tools-toggle');
const $toolsList   = document.getElementById('tools-list');

async function fetchTools() {
  try {
    const res = await fetch('/api/tools');
    if (!res.ok) return;
    const { tools } = await res.json();
    document.getElementById('tools-count').textContent = tools.length;
    $toolsList.innerHTML = '';
    for (const t of tools) {
      const li = document.createElement('li');
      li.innerHTML = '<span class="lock"></span><span class="nm"></span><span class="ds"></span>';
      li.querySelector('.lock').textContent = t.approval ? '🔒' : '·';
      li.querySelector('.nm').textContent = t.name;
      li.querySelector('.ds').textContent = t.description;
      li.title = `${t.name}${t.approval ? ' (실행 전 승인 필요)' : ''}\n${t.description}`;
      $toolsList.appendChild(li);
    }
  } catch (e) {
    console.warn('tools fetch failed:', e);
  }
}

$toolsToggle.addEventListener('click', () => {
  const open = $toolsToggle.getAttribute('aria-expanded') !== 'true';
  $toolsToggle.setAttribute('aria-expanded', String(open));
  $toolsList.hidden = !open;
});

// ── Streaming assistant message ───────────────────────────────────────────────
let _streamDiv      = null;
let _streamText     = '';
let _lastStreamText = '';  // voice TTS용 마지막 완성 텍스트
let _pendingProactiveId = null;  // 피드백 대기 중인 proactive 메시지 id (C3)
// 음성 피드백 키워드 — proactive 직후 짧게 말하면 수락/무시로 해석.
const _FB_ACCEPT = ['좋아', '고마워', '응', '그래', '확인', '오케이'];
const _FB_DISMISS = ['아니', '됐어', '무시', '괜찮아', '나중에', '아니야'];

function streamStart() {
  _streamText = '';
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.innerHTML = '<div class="role"><span class="indicator">▌</span><span></span></div><div class="body"><div class="agent-text"></div></div>';
  div.querySelector('.role span:last-child').textContent = AGENT_NAME;
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
  const line = lastLine(_streamText);
  if (line) showLive(line);
}

function streamEnd() {
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

  // Artifact 감지 — 큰 코드블록(8줄 이상)이면 패널에 표시
  if (_lastStreamText) {
    const artifact = extractArtifact(_lastStreamText);
    if (artifact) showArtifact(artifact.lang, artifact.code);
  }
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
          '<div class="role"><span class="indicator">▌</span><span></span></div>' +
          '<div class="body"><div class="agent-text"></div></div>';
        div.querySelector('.role span:last-child').textContent = AGENT_NAME;
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
  _streamDiv  = null;
  _streamText = '';
  _toolMsgs.clear();
  setInputEnabled(false);
  resetUsage();
  hideArtifact();
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
    logActivity('link lost — retrying', 'err');
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

// ── Agent hierarchy stack ─────────────────────────────────────────────────────
let _agentStack = []; // [{name: string|null}, ...] — 계층 추적용

function _agentBreadcrumb() {
  const names = _agentStack.map(a => a.name || '?').filter(Boolean);
  return names.length ? names.join(' → ') : null;
}

// ── Message router ────────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {

    case 'connected': {
      const sid = msg.session_id || '—';
      const model = msg.model || '—';
      _currentModel = model;
      $sessionIdLabel.textContent = sid;
      $sysModel.textContent       = model;
      $sysModel.title             = model;
      logActivity(`session ${sid} linked`, 'ok');
      fetchAgenda();
      fetchTools();
      if (msg.sessions) renderSessions(msg.sessions);
      if (msg.slash_commands) _slashCmds = msg.slash_commands;
      if (msg.voice && msg.voice.stt_mode) voice.setSttMode(msg.voice.stt_mode);
      setStatus('READY');
      setInputEnabled(true);
      HUD.setState('idle');
      break;
    }

    case 'agent_start': {
      clearTimeout(_awaitTimer);
      const isRoot = _agentStack.length === 0;
      _agentStack.push({ name: msg.agent_name || null });
      if (!isRoot && msg.agent_name) logActivity(`↳ ${msg.agent_name}`);
      const crumb = _agentBreadcrumb();
      setStatus(crumb ? `THINKING · ${crumb}` : 'THINKING', 'thinking');
      HUD.setState('thinking');
      if (isRoot) streamStart(); // 루트 에이전트만 메시지 컨테이너 초기화
      break;
    }

    case 'message_update':
      if (msg.text_delta) streamDelta(msg.text_delta);
      break;

    case 'stream_delta':
      streamDelta(msg.text);
      break;

    case 'agent_end': {
      if (_agentStack.length > 0) _agentStack.pop();

      if (_agentStack.length === 0) {
        // 루트 에이전트 종료 — 메시지 확정 + 입력 복원
        streamEnd();
        setStatus('READY');
        HUD.setState('idle');
        fetchAgenda();  // 이번 턴의 inner thought 가 open loop 를 남겼을 수 있다
        const usage = msg.final_message?.usage;
        if (usage) updateUsage(usage);
        if (_voiceMode && _lastStreamText) {
          voice.setProcessing();
          send({ type: 'voice_tts_request', text: _lastStreamText });
        } else {
          setInputEnabled(true);
        }
        _voiceMode = false;
      } else {
        // 서브 에이전트 종료 — 부모 계층으로 복귀
        const crumb = _agentBreadcrumb();
        setStatus(crumb ? `THINKING · ${crumb}` : 'THINKING', 'thinking');
        HUD.setState('thinking');
      }
      break;
    }

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
      logActivity(cmd ? `▸ ${name} · ${cmd}` : `▸ ${name}`, 'tool');
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
        logActivity(`${ok ? '✓' : '✗'} ${entry.name}`, ok ? 'ok' : 'err');
        _toolMsgs.delete(msg.tool_call_id);
      }
      setStatus('THINKING', 'thinking');
      HUD.setState('thinking');
      break;
    }

    case 'agent_error':
      streamEnd();
      logActivity(msg.message || 'Unknown error', 'err');
      appendMsg('SYS', 'err', escapeHtml(msg.message || 'Unknown error'));
      setStatus('ERROR', 'error');
      HUD.setState('error');
      setInputEnabled(true);
      setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, 3000);
      break;

    case 'inner_thought': {
      fetchAgenda();
      // 메인 응답과 구분된 메타인지 라인 (💭). interpretation이 없으면 표시 생략.
      const interp = (msg.interpretation || '').trim();
      if (interp) {
        const conf = Math.round((msg.confidence || 0) * 100);
        logActivity(`💭 ${msg.decision || 'silent'} · ${conf}%`);
        appendMsg('💭', 'thought',
          `${escapeHtml(interp)} <span class="thought-meta">(${escapeHtml(msg.decision || 'silent')} · ${conf}%)</span>`);
      }
      break;
    }

    case 'proactive_message': {
      // 시스템 비요청 발화 — filler(💬 대기) / proactive·answer(🔔 먼저 건넨 말).
      const ptext = (msg.text || '').trim();
      if (ptext) {
        const isFiller = msg.kind === 'filler';
        const div = appendMsg(isFiller ? '💬' : '🔔', 'proactive', escapeHtml(ptext));
        logActivity(`${isFiller ? '💬' : '🔔'} ${ptext}`, 'proactive');
        showLive(lastLine(ptext), CAPTION_HOLD_MS);
        // filler가 아닌 먼저 건넨 말엔 수락/무시 피드백 버튼 (C3).
        if (!isFiller && msg.message_id) {
          _pendingProactiveId = msg.message_id;
          const bar = document.createElement('div');
          bar.className = 'proactive-fb';
          bar.innerHTML = '<button class="fb-yes">👍 도움됨</button><button class="fb-no">👎 무시</button>';
          div.querySelector('.body').appendChild(bar);
          const finish = (accepted) => {
            send({ type: 'proactive_feedback', id: msg.message_id, accepted });
            bar.querySelectorAll('button').forEach((b) => { b.disabled = true; });
            bar.classList.add('done');
            if (_pendingProactiveId === msg.message_id) _pendingProactiveId = null;
          };
          bar.querySelector('.fb-yes').onclick = () => finish(true);
          bar.querySelector('.fb-no').onclick = () => finish(false);
        }
        // voice 모드면 비요청 발화도 즉시 읽어준다 — filler는 대기 체감을 줄이는 핵심.
        if (_voiceMode || msg.speak) {
          voice.setProcessing();
          send({ type: 'voice_tts_request', text: ptext });
        }
      }
      break;
    }

    case 'error':
      voice.setIdle();  // TTS 오류면 '음성 처리 중' 상태를 풀어 준다
      appendMsg('SYS', 'err', escapeHtml(msg.message || 'Error'));
      logActivity(msg.message || 'Error', 'err');
      setStatus('ERROR', 'error');
      HUD.setState('error');
      setInputEnabled(true);
      setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, 3000);
      break;

    case 'reminder':
      showNotice(msg);
      break;

    case 'approval_request':
      showApproval(msg.id, msg.command, msg.reason);
      logActivity(`⚡ approval · ${msg.command || ''}`, 'tool');
      break;

    case 'voice_tts_audio':
      if (msg.data) {
        // 백엔드 TTS (Supertonic-3 WAV)
        voice.playAudioBase64(msg.data, msg.mime || 'audio/wav');
      } else if (msg.text) {
        // 브라우저 TTS fallback (BrowserTTSProvider)
        voice.speakBrowser(msg.text);
      } else {
        voice.setIdle();
      }
      break;

    case 'voice_stt_result':
      // 서버 STT (Whisper 등) 전사 결과
      if (msg.error) {
        appendMsg('SYS', 'err', escapeHtml(`STT 오류: ${msg.error}`));
        voice.setIdle();
      } else if (msg.text && msg.text.trim()) {
        voice.receiveTranscript(msg.text);
      } else {
        appendMsg('SYS', 'err', '음성을 인식하지 못했습니다.');
        voice.setIdle();
      }
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
  const ctx = getSlashContext();
  if (ctx) {
    // 커서 앞의 /fragment 만 /cmdname␣ 으로 교체, 뒤 텍스트는 보존
    const val      = $input.value;
    const inserted = '/' + cmd.name + ' ';
    $input.value   = val.slice(0, ctx.slashStart) + inserted + val.slice(ctx.slashEnd);
    const newPos   = ctx.slashStart + inserted.length;
    $input.setSelectionRange(newPos, newPos);
  } else {
    $input.value = '/' + cmd.name + ' ';
  }
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

// 커서 직전 텍스트에서 /command 컨텍스트 추출
// 반환: { query, slashStart, slashEnd } 또는 null
function getSlashContext() {
  const val    = $input.value;
  const cursor = $input.selectionStart ?? val.length;
  const before = val.slice(0, cursor);
  // /command 가 문장 맨앞이거나 공백 뒤에 위치할 때만 매칭
  const m = before.match(/(?:^|\s)(\/([a-zA-Z0-9_?-]*))$/);
  if (!m) return null;
  const slashStart = cursor - m[1].length;
  return { query: m[2].toLowerCase(), slashStart, slashEnd: cursor };
}

// Input event: update highlight + show/filter popup when typing /cmd
$input.addEventListener('input', () => {
  updateHighlight();
  const ctx = getSlashContext();
  if (ctx) {
    const filtered = _slashCmds.filter(c => c.name.startsWith(ctx.query));
    if (filtered.length > 0) { showSlashPopup(filtered); return; }
  }
  hideSlashPopup();
});

// 커서 이동(클릭, 방향키)으로 슬래시 컨텍스트가 바뀔 때도 팝업 재평가
$input.addEventListener('keyup', (e) => {
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
    const ctx = getSlashContext();
    if (ctx) {
      const filtered = _slashCmds.filter(c => c.name.startsWith(ctx.query));
      if (filtered.length > 0) { showSlashPopup(filtered); return; }
    }
    hideSlashPopup();
  }
});
$input.addEventListener('click', () => {
  const ctx = getSlashContext();
  if (ctx) {
    const filtered = _slashCmds.filter(c => c.name.startsWith(ctx.query));
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

// 보내는 즉시 THINKING — 서버는 첫 이벤트(agent_start) 전에 inner thought(LLM 호출)를
// 먼저 돌리므로 몇 초간 아무 이벤트도 오지 않는다. 그동안 HUD 가 쉬는 것처럼 보이지 않게 한다.
// 응답이 끝내 오지 않으면 90초 뒤 원래대로 돌린다.
const AWAIT_TIMEOUT_MS = 90000;
let _awaitTimer = null;

function beginAwaitingReply() {
  setStatus('THINKING', 'thinking');
  HUD.setState('thinking');
  clearTimeout(_awaitTimer);
  _awaitTimer = setTimeout(() => {
    if (_agentStack.length === 0) { setStatus('READY'); HUD.setState('idle'); }
  }, AWAIT_TIMEOUT_MS);
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
  beginAwaitingReply();
  if (/(^|\s)\/schedule\b/.test(text)) askNotificationPermission();
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
let _voiceMode = false;  // 현재 음성으로 시작된 요청인지
const $sphereWrap = document.querySelector('.sphere-wrap');
const $sphereHit  = document.getElementById('sphere-hit');

const voice = new VoiceManager({
  onTranscript(transcript) {
    if (!transcript.trim()) return;
    // proactive 직후 짧은 음성 피드백을 수락/무시로 해석 (C3, voice).
    if (_pendingProactiveId) {
      const t = transcript.trim().replace(/[.!?…]/g, '');
      if (_FB_ACCEPT.includes(t) || _FB_DISMISS.includes(t)) {
        const accepted = _FB_ACCEPT.includes(t);
        send({ type: 'proactive_feedback', id: _pendingProactiveId, accepted });
        _pendingProactiveId = null;
        appendMsg('SYS', 'sys', accepted ? '피드백: 도움됨' : '피드백: 무시');
        return;
      }
    }
    _voiceMode = true;
    // 인식된 텍스트를 입력창에 표시
    $input.value = transcript;
    updateHighlight();
    // 즉시 에이전트로 전송 (appendMsg + WS)
    appendMsg('USER', 'user', escapeHtml(transcript));
    $input.value = '';
    updateHighlight();
    setInputEnabled(false);
    send({ type: 'user_message', text: transcript });
    beginAwaitingReply();
  },
  onStateChange(state) {
    // 구체 시각 상태 반영
    $sphereWrap.classList.remove('voice-listening', 'voice-speaking', 'voice-processing');
    if (state !== 'idle') $sphereWrap.classList.add(`voice-${state}`);

    if (state === 'listening') {
      setStatus('LISTENING', 'listening');
      HUD.setState('listening');
    } else if (state === 'speaking') {
      setStatus('SPEAKING', 'speaking');
      HUD.setState('speaking');
    } else if (state === 'processing') {
      // 에이전트 처리 중 — 기존 UI가 담당
    } else {
      // idle: TTS 종료 or 오류 → input 복원 + 상태 표시 초기화
      if ($statusText.textContent === 'LISTENING' || $statusText.textContent === 'SPEAKING') {
        setStatus('READY');
        HUD.setState('idle');
      }
      setInputEnabled(true);
    }
  },
  onError(msg) {
    appendMsg('SYS', 'err', escapeHtml(msg));
  },
  onAudioCaptured(base64, mime) {
    // 서버 STT 모드: 녹음된 오디오를 백엔드로 전송 → voice_stt_result 수신
    send({ type: 'voice_stt_submit', data: base64, mime, sample_rate: 16000 });
  },
});
window.voiceManager = voice;

// 구체 클릭 → voice mode 토글
$sphereHit.addEventListener('click', () => {
  if (!voice.supported) {
    appendMsg('SYS', 'err', 'Web Speech API를 지원하지 않는 브라우저입니다. Chrome을 사용해 주세요.');
    return;
  }
  voice.toggle();
});


// ── Conversation card collapse ────────────────────────────────────────────────
// 접힘 여부는 뷰어별 편의 설정이라 localStorage 에만 둔다(없어도 동작).
const CHAT_KEY = 'hud.chatCollapsed';
try {
  if (localStorage.getItem(CHAT_KEY) === '1') document.body.classList.add('chat-collapsed');
} catch { /* storage 차단 — 기본(펼침)으로 */ }
document.getElementById('chat-toggle').addEventListener('click', () => {
  const next = !document.body.classList.contains('chat-collapsed');
  document.body.classList.toggle('chat-collapsed', next);
  try { localStorage.setItem(CHAT_KEY, next ? '1' : '0'); } catch { /* 무시 */ }
  if (!next) $messages.scrollTop = $messages.scrollHeight;
});

// ── Mobile drawer ─────────────────────────────────────────────────────────────
// 좁은 화면에서 세션·활동·시스템 카드(.hud-side)는 오버레이 드로어가 된다(CSS @media 860px 이하).
// 데스크탑에서는 버튼이 숨겨져 있어 이 코드가 실행될 일이 없다.
const $drawerBtn   = document.getElementById('drawer-btn');
const $drawerScrim = document.getElementById('drawer-scrim');

function setDrawer(open) {
  document.body.classList.toggle('drawer-open', open);
  $drawerScrim.hidden = !open;
  $drawerBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  $drawerBtn.setAttribute('aria-label', open ? '패널 닫기' : '패널 열기');
}

$drawerBtn.addEventListener('click', () => {
  setDrawer(!document.body.classList.contains('drawer-open'));
});
$drawerScrim.addEventListener('click', () => setDrawer(false));
// 세션을 고르면 드로어를 닫아 바로 대화로 돌아간다.
document.getElementById('session-list').addEventListener('click', () => setDrawer(false));
document.getElementById('new-session-btn').addEventListener('click', () => setDrawer(false));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') setDrawer(false);
});
// 데스크탑 폭으로 돌아오면 드로어 상태를 남기지 않는다.
window.addEventListener('resize', () => {
  if (window.innerWidth > 860) setDrawer(false);
});


// ── Boot ──────────────────────────────────────────────────────────────────────
showQuote();
setInputEnabled(false);
connect('default');
