// ION 띠 — 플랫폼 감시(Ion)가 연 사고를 보이고 버튼으로 답한다. /ion/ 은 nginx 가 Ion 컨테이너로 보내 백엔드가 죽어도 산다.
import { apiFetch, getToken } from './api.js';
import { logActivity } from './shell.js';

const LABELS = { restart: '재기동', stop: '멈춤', pause: '작업 멈춤', ignore: '무시' };
// SSE 가 끊겨 있어도 상태는 이 주기로 다시 읽는다
const REFRESH_MS = 60_000;
// 답한 사고는 결과를 잠깐 보이고 지운다
const DONE_LINGER_MS = 8_000;
const $strip = document.getElementById('ion-strip');
const $list = document.getElementById('ion-list');
const rows = new Map(); // 사고 id → { incident, el }
const bridge = window.jarvisDesktop;

function render() {
  $strip.hidden = rows.size === 0;
}

function row(incident) {
  const el = document.createElement('li');
  el.className = 'ion-item';
  const title = document.createElement('span');
  title.className = 'ion-title';
  title.textContent = incident.title || incident.kind;
  const detail = document.createElement('span');
  detail.className = 'ion-detail';
  detail.textContent = incident.detail || '';
  el.append(title, detail);
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
    btn.addEventListener('click', () => respond(incident.id, action, el));
    el.append(btn);
  });
  return el;
}

function upsert(incident) {
  const prev = rows.get(incident.id);
  const el = row(incident);
  if (prev) prev.el.replaceWith(el);
  else $list.append(el);
  rows.set(incident.id, { incident, el });
  if (incident.response) setTimeout(() => remove(incident.id), DONE_LINGER_MS);
}

function remove(id) {
  const prev = rows.get(id);
  if (!prev) return;
  prev.el.remove();
  rows.delete(id);
  render();
}

// 서버의 열린 사고 목록에 맞춘다. 답한 사고는 결과를 보이는 동안 남긴다
function sync(incidents) {
  const live = new Set(incidents.map((i) => i.id));
  incidents.forEach(upsert);
  for (const [id, { incident }] of rows) {
    if (!live.has(id) && !incident.response) remove(id);
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

async function respond(id, action, el) {
  el.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    const res = await apiFetch(`/ion/incidents/${encodeURIComponent(id)}/respond`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
    });
    if (!res.ok) {
      logActivity(`ion · ${LABELS[action]} 실패 · ${res.status}`, 'err');
      el.querySelectorAll('button').forEach((b) => { b.disabled = false; });
      return;
    }
    const { incident } = await res.json();
    upsert(incident);
    logActivity(`ion · ${LABELS[action]} · ${incident.action_result || ''}`, 'ok');
  } catch {
    logActivity(`ion · ${LABELS[action]} 실패 · 연결 없음`, 'err');
    el.querySelectorAll('button').forEach((b) => { b.disabled = false; });
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
    upsert({ id: p.id, kind: p.kind, target: p.target, detail: p.body, title: p.title, actions: p.actions });
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

load();
subscribe();
setInterval(load, REFRESH_MS);
