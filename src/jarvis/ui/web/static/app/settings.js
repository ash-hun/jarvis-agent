// Settings 화면 — 서버가 준 필드 정의(fields)로 폼을 그리고, 바뀐 값만 PUT 한다. 데스크톱 앱이면 앱 설정과 재시작도.
import { apiFetch } from './api.js';
import { onViewOpen } from './view.js';

const SECTION_LABEL = { voice: 'Voice', proactive: 'Proactive', thought: 'Thought', focus: 'Focus' };
// 데스크톱 셸 설정. 값의 정본은 셸(desktop/desktop_settings.js)이고 여기서는 보여 주고 보낸다
const DESKTOP_FIELDS = {
  hotkey: { title: '전역 단축키 (듣기 시작)', type: 'string' },
  autoLaunch: { title: '로그인 때 자동 실행', type: 'boolean' },
  startBackend: { title: '백엔드가 없으면 docker compose 로 띄우기', type: 'boolean' },
  backendUrl: { title: '백엔드 주소 (재시작 후 반영)', type: 'string' },
};

const $form = document.getElementById('settings-form');
const $fields = document.getElementById('settings-fields');
const $path = document.getElementById('settings-path');
const $status = document.getElementById('settings-status');
const $restart = document.getElementById('settings-restart');
const $effective = document.getElementById('settings-effective');
const $desktopCard = document.getElementById('desktop-card');
const $desktopFields = document.getElementById('desktop-fields');
const $desktopStatus = document.getElementById('desktop-status');
const $desktopSave = document.getElementById('desktop-save');

let _loaded = {};  // section → field → 적용값. 바뀐 값만 보내려고 들고 있다
let _desktop = {};

function status($el, text, cls = '') {
  $el.textContent = text;
  $el.className = `settings-status ${cls}`.trim();
}

function inputFor(id, spec, value) {
  let input;
  if (spec.enum) {
    input = document.createElement('select');
    for (const opt of spec.enum) {
      const o = document.createElement('option');
      o.value = opt;
      o.textContent = opt === '' ? '(없음)' : opt;
      input.appendChild(o);
    }
    input.value = value ?? '';
  } else if (spec.type === 'boolean') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!value;
  } else if (spec.type === 'number' || spec.type === 'integer') {
    input = document.createElement('input');
    input.type = 'number';
    input.step = spec.type === 'integer' ? '1' : '0.01';
    if (spec.minimum !== undefined) input.min = String(spec.minimum);
    if (spec.maximum !== undefined) input.max = String(spec.maximum);
    input.value = value ?? '';
  } else {
    input = document.createElement('input');
    input.type = 'text';
    if (spec.pattern) input.pattern = spec.pattern;
    input.value = value ?? '';
  }
  input.id = id;
  input.dataset.type = spec.enum ? 'enum' : spec.type;
  return input;
}

function readInput(input) {
  if (input.dataset.type === 'boolean') return input.checked;
  if (input.dataset.type === 'number') return input.value === '' ? null : Number(input.value);
  if (input.dataset.type === 'integer') return input.value === '' ? null : Math.round(Number(input.value));
  return input.value;
}

function row(id, spec, value, pending) {
  const wrap = document.createElement('div');
  wrap.className = pending ? 'settings-row pending' : 'settings-row';
  const label = document.createElement('label');
  label.htmlFor = id;
  label.textContent = spec.title;
  wrap.append(label, inputFor(id, spec, value));
  return wrap;
}

function renderForm(body) {
  _loaded = body.editable || {};
  const pending = body.pending || {};
  $path.textContent = body.path || '—';
  $path.title = body.path || '';
  const groups = Object.entries(body.fields || {}).map(([section, fields]) => {
    const fs = document.createElement('fieldset');
    fs.className = 'settings-group';
    const legend = document.createElement('legend');
    legend.textContent = SECTION_LABEL[section] || section;
    fs.appendChild(legend);
    for (const [name, spec] of Object.entries(fields)) {
      const saved = pending[section] && name in pending[section] ? pending[section][name] : _loaded[section]?.[name];
      fs.appendChild(row(`set-${section}-${name}`, spec, saved, !!(pending[section] && name in pending[section])));
    }
    return fs;
  });
  $fields.replaceChildren(...groups);
  $effective.textContent = JSON.stringify(body.effective || {}, null, 2);
  const waiting = Object.keys(pending).length > 0;
  status($status, waiting ? '저장됨 · 백엔드를 다시 띄우면 반영됩니다' : '', waiting ? 'warn' : '');
  $restart.hidden = !(waiting && window.jarvisDesktop);
}

// 화면의 값 중 지금 적용값과 다른 것만. 같은 값을 다시 보내지 않으니 저장을 여러 번 눌러도 결과가 같다
function collectPatch(fields) {
  const patch = {};
  for (const [section, specs] of Object.entries(fields)) {
    for (const name of Object.keys(specs)) {
      const input = document.getElementById(`set-${section}-${name}`);
      if (!input) continue;
      const value = readInput(input);
      if (value === null || value === _loaded[section]?.[name]) continue;
      (patch[section] ||= {})[name] = value;
    }
  }
  return patch;
}

let _fields = {};

export async function loadSettings() {
  try {
    const res = await apiFetch('/api/settings');
    if (!res.ok) { status($status, `설정을 읽지 못했습니다 (${res.status})`, 'err'); return; }
    const body = await res.json();
    _fields = body.fields || {};
    renderForm(body);
  } catch {
    status($status, '백엔드에 연결되지 않았습니다', 'err');
  }
  await loadDesktop();
}

$form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const bad = $form.querySelector(':invalid');
  if (bad) { status($status, '범위나 형식이 맞지 않는 값이 있습니다', 'err'); bad.focus(); return; }
  const patch = collectPatch(_fields);
  if (!Object.keys(patch).length) { status($status, '바뀐 값이 없습니다'); return; }
  try {
    const res = await apiFetch('/api/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    });
    if (!res.ok) { status($status, `저장 실패 (${res.status})`, 'err'); return; }
    renderForm(await res.json());
  } catch {
    status($status, '백엔드에 연결되지 않았습니다', 'err');
  }
});

$restart.addEventListener('click', async () => {
  if (!window.jarvisDesktop) return;
  $restart.disabled = true;
  status($status, '백엔드를 다시 띄우는 중…', 'warn');
  const result = await window.jarvisDesktop.restartBackend().catch((err) => ({ ok: false, error: String(err) }));
  $restart.disabled = false;
  // 성공하면 ws 가 끊겼다 다시 붙고, 셸이 페이지를 새로 읽는다
  if (!result.ok) status($status, `재시작 실패: ${result.error || '알 수 없음'}`, 'err');
});

async function loadDesktop() {
  const bridge = window.jarvisDesktop;
  $desktopCard.hidden = !bridge;
  if (!bridge) return;
  _desktop = await bridge.getSettings().catch(() => ({}));
  $desktopFields.replaceChildren(...Object.entries(DESKTOP_FIELDS).map(
    ([name, spec]) => row(`desk-${name}`, spec, _desktop[name], false),
  ));
}

$desktopSave.addEventListener('click', async () => {
  const bridge = window.jarvisDesktop;
  if (!bridge) return;
  const next = {};
  for (const name of Object.keys(DESKTOP_FIELDS)) {
    const input = document.getElementById(`desk-${name}`);
    if (input) next[name] = readInput(input);
  }
  const result = await bridge.setSettings(next).catch((err) => ({ ok: false, error: String(err) }));
  if (result.ok) { _desktop = result.settings || next; status($desktopStatus, '저장됨'); }
  else status($desktopStatus, `저장 실패: ${result.error || '알 수 없음'}`, 'err');
});

onViewOpen('settings', loadSettings);
