// AGENDA 카드(스케줄 + open loops + 최근 닫힌 약속)와 스케줄 알림.
// 서버에 변경 이벤트가 없으므로 접속·inner thought·응답 종료·조작 직후, 그리고 1분마다 다시 불러온다.
import { AGENT_NAME } from './brand.js';
import { apiFetch } from './api.js';
import { escapeHtml, renderMarkdown, attachCopyBtns } from './markdown.js';
import { logActivity, showLive, lastLine, CAPTION_HOLD_MS } from './shell.js';
import { appendMsg } from './messages.js';
import { requestSpeech } from './voice-ui.js';
import { loadAgents, isTeam, agentTag } from './agents.js';

const $scheduleList = document.getElementById('schedule-list');
const $openloopList = document.getElementById('openloop-list');
const $agendaCount  = document.getElementById('agenda-count');
const $closedBox    = document.getElementById('closedloop-box');
const $closedList   = document.getElementById('closedloop-list');
const $closedCount  = document.getElementById('closedloop-count');

const REFRESH_MS = 60000;
const pad = (n) => String(n).padStart(2, '0');
const CLOSED_LABEL = { done: '완료', dismissed: '무시', expired: '만료' };

// 오늘이면 HH:MM, 내일이면 '내일 HH:MM', 그 뒤면 'M/D HH:MM'. 24시간 안이면 남은 시간도.
function fmtWhen(iso) {
  const d = new Date(iso);
  const now = new Date();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const dayDiff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) -
                              new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  const day = dayDiff === 0 ? '' : dayDiff === 1 ? '내일 ' : `${d.getMonth() + 1}/${d.getDate()} `;
  const mins = Math.round((d - now) / 60000);
  const left = mins < 60 ? `${Math.max(mins, 0)}분 후` : mins < 1440 ? `${Math.round(mins / 60)}시간 후` : '';
  return `${day}${hm}${left ? ' · ' + left : ''}`;
}

// 지난 시각. 오늘이면 HH:MM, 아니면 M/D HH:MM.
function fmtPast(ms) {
  const d = new Date(ms);
  const sameDay = d.toDateString() === new Date().toDateString();
  return `${sameDay ? '' : `${d.getMonth() + 1}/${d.getDate()} `}${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function agendaItem(text, when, cls = '', agent = null) {
  const li = document.createElement('li');
  li.className = `agenda-item ${cls}`.trim();
  li.innerHTML = '<div class="what"><span class="txt"></span><span class="when"></span></div><div class="acts"></div>';
  li.querySelector('.txt').textContent = text;
  li.querySelector('.what').title = text;
  li.querySelector('.when').textContent = when;
  // 여러 에이전트의 약속이 한 카드에 섞이므로 누구 것인지 이름과 색으로 단다
  if (isTeam()) {
    li.querySelector('.when').prepend(agentTag(agent || 'main'));
    li.dataset.agent = agent || 'main';
  }
  return li;
}

function renderAgenda({ schedules = [], open_loops = [], closed_loops = [] }) {
  $scheduleList.innerHTML = '';
  for (const t of schedules) {
    let when = t.next_run ? fmtWhen(t.next_run) : (t.enabled ? '다음 실행 없음' : '꺼짐');
    if (t.run_until) {
      const u = new Date(t.run_until);
      when += ` · ~${u.getMonth() + 1}/${u.getDate()} ${pad(u.getHours())}:${pad(u.getMinutes())}`;
    }
    if (t.once) when += ` · 한 번 · ${t.kind === 'reminder' ? '알림' : '작업'}`;
    // /schedule 로 만든 작업의 description 은 자동 문구라, 사용자가 쓴 프롬프트를 보여준다
    const fromSlash = t.name.startsWith('slash-') || t.name.startsWith('once-');
    const label = fromSlash ? t.prompt : (t.description || t.prompt || t.name);
    const li = agendaItem(label, when, t.enabled ? '' : 'off', t.agent);
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
    const li = agendaItem(lp.description, when, '', lp.agent);
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

  $closedList.innerHTML = '';
  for (const lp of closed_loops) {
    const li = agendaItem(lp.description, `${CLOSED_LABEL[lp.status] || lp.status} · ${fmtPast(lp.updated_at)}`, '', lp.agent);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'icon-btn reopen';
    b.textContent = '↺';
    b.title = '되살리기';
    b.addEventListener('click', () => reopenOpenLoop(lp, li));
    li.querySelector('.acts').appendChild(b);
    $closedList.appendChild(li);
  }
  $closedBox.hidden = closed_loops.length === 0;
  $closedCount.textContent = closed_loops.length ? pad(closed_loops.length) : '';

  const active = schedules.filter(t => t.enabled).length + open_loops.length;
  $agendaCount.textContent = pad(active);
}

export async function fetchAgenda() {
  try {
    const [res] = await Promise.all([apiFetch('/api/agenda'), loadAgents()]);
    if (res.ok) renderAgenda(await res.json());
  } catch (e) {
    console.warn('agenda fetch failed:', e);
  }
}

async function closeOpenLoop(loop, status, li) {
  li.classList.add('leaving');
  const res = await apiFetch(`/api/openloops/${encodeURIComponent(loop.id)}`, {
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

async function reopenOpenLoop(loop, li) {
  li.classList.add('leaving');
  const res = await apiFetch(`/api/openloops/${encodeURIComponent(loop.id)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'open' }),
  }).catch(() => null);
  if (res && res.ok) {
    logActivity(`↺ 되살림 · ${loop.description}`, 'ok');
  } else if (res && res.status === 409) {
    // 기한이나 수명이 지나 열자마자 다시 만료될 약속이다
    logActivity(`기한이 지나 되살리지 않음 · ${loop.description}`, 'err');
  } else {
    logActivity(`open loop 되살리기 실패 · ${loop.description}`, 'err');
  }
  fetchAgenda();
}

async function toggleSchedule(name, enabled) {
  const res = await apiFetch(`/api/schedules/${encodeURIComponent(name)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }).catch(() => null);
  logActivity(res && res.ok ? `⏱ ${name} ${enabled ? '켜짐' : '꺼짐'}` : `스케줄 변경 실패 · ${name}`, res && res.ok ? '' : 'err');
  fetchAgenda();
}

setInterval(fetchAgenda, REFRESH_MS);

// ── 스케줄 알림 ───────────────────────────────────────────────────────────────
// 서버가 스케줄 실행 결과를 {type:'reminder'} 로 방송한다. 대화 🔔 · 캡션 · Activity ·
// 브라우저 시스템 알림(탭이 뒤에 있을 때) · 음성으로 알린다.
function noticeSuffix(n) {
  if (n.missed) return ' (놓친 알림)';
  if (n.delayed_sec > 60) return ` (지연 ${Math.round(n.delayed_sec / 60)}분)`;
  return '';
}

export function showNotice(n) {
  const suffix = noticeSuffix(n);
  const text = (n.text || '').trim();
  // 작업(에이전트가 돈 task, 도구를 바로 부른 tool)이면 무엇을 실행한 결과인지 제목을 붙인다
  const result = n.kind === 'task' || n.kind === 'tool';
  const header = result ? `<div class="notice-title">⏱ ${escapeHtml(n.title || '')}${escapeHtml(suffix)}</div>` : '';
  const body = result
    ? header + renderMarkdown(text)
    : `${escapeHtml(text)}${suffix ? `<span class="thought-meta">${escapeHtml(suffix)}</span>` : ''}`;
  const div = appendMsg('🔔', n.error ? 'err' : 'proactive', body);
  attachCopyBtns(div);

  logActivity(`🔔 ${result ? n.title : text}${suffix}`, n.error ? 'err' : 'proactive');
  showLive(lastLine(text) || n.title || '', CAPTION_HOLD_MS);

  if ('Notification' in window && Notification.permission === 'granted' &&
      (document.hidden || !document.hasFocus())) {
    try {
      new Notification(`${AGENT_NAME}${suffix}`, { body: text.slice(0, 240), tag: n.id });
    } catch (e) { /* 일부 브라우저는 페이지에서 직접 생성을 막는다 */ }
  }

  // 놓친 알림은 한꺼번에 몰려올 수 있어 읽지 않는다
  if (!n.missed && text) requestSpeech(text.slice(0, 400), { source: 'reminder' });
  fetchAgenda();  // 한 번 실행 알림은 울린 뒤 목록에서 빠진다
}
