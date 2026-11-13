// ION 띠와 끼어들기 — 플랫폼 감시(Ion)가 연 사고를 띠와 지금 대화에 보이고, 구체 뒤 배경을 심각도로 물들이며, 버튼으로 답한다.
// /ion/ 은 nginx 가 Ion 컨테이너로 보내 백엔드가 죽어도 산다.
import { apiFetch, getToken } from './api.js';
import { appendMsg } from './messages.js';
import { logActivity } from './shell.js';

const LABELS = { restart: '재기동', stop: '멈춤', pause: '작업 멈춤', ignore: '무시' };
const RANK = { critical: 2, warning: 1 };
// SSE 가 끊겨 있어도 상태는 이 주기로 다시 읽는다
const REFRESH_MS = 60_000;
// 답한 사고는 띠에 결과를 잠깐 보이고 지운다. 대화 카드는 남는다
const DONE_LINGER_MS = 8_000;
const $strip = document.getElementById('ion-strip');
const $list = document.getElementById('ion-list');
const rows = new Map(); // 사고 id → { incident, el, card }
const bridge = window.jarvisDesktop;

function worst() {
  let top = '';
  for (const { incident } of rows.values()) {
    if (!incident.response && (RANK[incident.severity] || 0) > (RANK[top] || 0)) top = incident.severity;
  }
  return top;
}

function render() {
  $strip.hidden = rows.size === 0;
  // 연결 끊김 배너가 띠 아래로 비키도록 높이를 알린다
  document.documentElement.style.setProperty('--ion-h', $strip.hidden ? '0px' : `${$strip.offsetHeight}px`);
  const severity = worst();
  if (severity) document.body.dataset.ion = severity;
  else delete document.body.dataset.ion;
}

// 띠의 한 줄과 대화 카드의 본문이 같은 꼴이다
function line(incident, onDone) {
  const el = document.createElement('div');
  el.className = 'ion-item';
  const title = document.createElement('span');
  title.className = 'ion-title';
  title.textContent = incident.title || incident.kind;
  const detail = document.createElement('span');
  detail.className = 'ion-detail';
  detail.textContent = incident.detail || '';
  el.append(title, detail);
  if (incident.closed_ms && !incident.response) {
    const result = document.createElement('span');
    result.className = 'ion-result';
    result.textContent = '해결됨';
    el.append(result);
    return el;
  }
  if (incident.response) {
    const result = document.createElement('span');
    result.className = 'ion-result';
    result.textContent = `${LABELS[incident.response] || incident.response} · ${incident.action_result || ''}`;
    el.append(result);
    return el;
  }
  (incident.actions || ['ignore']).forEach((action, i) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = LABELS[action] || action;
    if (i === 0) btn.classList.add('primary');
    btn.addEventListener('click', () => respond(incident.id, action));
    el.append(btn);
  });
  return el;
}

function fill(card, incident) {
  const body = card.querySelector('.body');
  body.replaceChildren(line(incident));
}

function upsert(incident) {
  const prev = rows.get(incident.id);
  const el = document.createElement('li');
  el.append(line(incident));
  if (prev) prev.el.replaceWith(el);
  else $list.append(el);
  // 끼어들기: 지금 어느 에이전트의 대화든 카드 하나. 세션을 바꾸면 messages-reset 때 다시 끼운다
  let card = prev?.card;
  if (!card || !card.isConnected) card = appendMsg('ION', 'ion');
  fill(card, incident);
  rows.set(incident.id, { incident, el, card });
  if (incident.response) setTimeout(() => removeFromStrip(incident.id), DONE_LINGER_MS);
}

function removeFromStrip(id) {
  const prev = rows.get(id);
  if (!prev) return;
  prev.el.remove();
  rows.delete(id);
  render();
}

// 서버의 열린 사고 목록에 맞춘다. 답한 사고는 결과를 보이는 동안 남기고, 닫힌 사고는 카드에 해결됨을 적는다
function sync(incidents) {
  const live = new Set(incidents.map((i) => i.id));
  incidents.forEach(upsert);
  for (const [id, { incident, card }] of rows) {
    if (!live.has(id) && !incident.response) {
      if (card?.isConnected) fill(card, { ...incident, closed_ms: Date.now() });
      removeFromStrip(id);
    }
  }
  render();
}

async function load() {
  try {
    const res = await apiFetch('/ion/status');
    if (!res.ok) return;
    sync((await res.json()).incidents || []);
  } catch {
    // Ion 이 없거나 nginx 밖(개발 서버)이면 띠는 그냥 숨긴 채 둔다
  }
}

function setBusy(id, busy) {
  const row = rows.get(id);
  if (!row) return;
  [row.el, row.card].forEach((root) => root?.querySelectorAll('button').forEach((b) => { b.disabled = busy; }));
}

async function respond(id, action) {
  setBusy(id, true);
  try {
    const res = await apiFetch(`/ion/incidents/${encodeURIComponent(id)}/respond`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
    });
    if (!res.ok) {
      logActivity(`ion · ${LABELS[action]} 실패 · ${res.status}`, 'err');
      setBusy(id, false);
      return;
    }
    const { incident } = await res.json();
    upsert(incident);
    render();
    logActivity(`ion · ${LABELS[action]} · ${incident.action_result || ''}`, 'ok');
  } catch {
    logActivity(`ion · ${LABELS[action]} 실패 · 연결 없음`, 'err');
    setBusy(id, false);
  }
}

// 데스크톱 앱은 창이 숨어 있어도 이 페이지가 살아 있어 OS 알림을 띄울 수 있다. 브라우저는 이미 허락한 경우만
function notify(payload) {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default' && bridge) {
    Notification.requestPermission().then(() => notify(payload)).catch(() => {});
    return;
  }
  if (Notification.permission !== 'granted') return;
  const n = new Notification(payload.title, { body: payload.body, tag: payload.tag });
  n.onclick = () => window.focus();
}

function subscribe() {
  const token = getToken();
  const source = new EventSource(`/ion/events${token ? `?token=${encodeURIComponent(token)}` : ''}`);
  source.addEventListener('incident', (event) => {
    const p = JSON.parse(event.data);
    upsert({ id: p.id, kind: p.kind, target: p.target, detail: p.body, title: p.title, actions: p.actions, severity: p.severity });
    render();
    logActivity(`ion · ${p.title}`, 'err');
    notify(p);
  });
  source.addEventListener('incident_update', (event) => {
    upsert(JSON.parse(event.data).incident);
    render();
  });
  // 다시 붙을 때마다(Ion 재시작 뒤 등) 놓친 사고를 목록으로 맞춘다
  source.onopen = load;
}

// 세션을 바꿔 대화가 비면 열린 사고 카드를 새 대화에 다시 끼운다
window.addEventListener('jarvis:messages-reset', () => {
  for (const row of rows.values()) {
    if (row.incident.response) continue;
    row.card = appendMsg('ION', 'ion');
    fill(row.card, row.incident);
  }
});

load();
subscribe();
setInterval(load, REFRESH_MS);
