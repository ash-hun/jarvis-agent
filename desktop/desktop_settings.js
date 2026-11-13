// 데스크톱 셸 설정(단축키, 자동 실행, 백엔드 주소) 읽기와 검증, 원자적 저장. electron 없이 시험할 수 있게 fs 만 쓴다.
const fs = require('node:fs');
const path = require('node:path');

const DEFAULTS = Object.freeze({
  hotkey: 'CommandOrControl+Shift+J',
  autoLaunch: false,
  backendUrl: 'http://127.0.0.1:7777',
});
// 셸이 띄우는 페이지는 이 기계 안의 백엔드만. preload 브리지가 다른 출처에 열리지 않게 한다
const ALLOWED_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);
const HOTKEY = /^[A-Za-z0-9+]{1,64}$/;

function normalizeBackendUrl(value) {
  let url;
  try { url = new URL(String(value)); } catch { return null; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (!ALLOWED_HOSTS.has(url.hostname)) return null;
  return url.origin;
}

// 알 수 없는 키는 버리고, 형식이 틀린 값은 오류로 돌려준다. 같은 입력이면 같은 결과다
function normalize(input) {
  const errors = [];
  const out = { ...DEFAULTS };
  const src = input && typeof input === 'object' ? input : {};
  if ('hotkey' in src) {
    if (typeof src.hotkey === 'string' && HOTKEY.test(src.hotkey)) out.hotkey = src.hotkey;
    else errors.push('hotkey: 영문, 숫자, + 만 (예: CommandOrControl+Shift+J)');
  }
  if ('autoLaunch' in src) {
    if (typeof src.autoLaunch === 'boolean') out.autoLaunch = src.autoLaunch;
    else errors.push('autoLaunch: true 또는 false');
  }
  if ('backendUrl' in src) {
    const origin = normalizeBackendUrl(src.backendUrl);
    if (origin) out.backendUrl = origin;
    else errors.push('backendUrl: 이 기계의 http(s) 주소만 (127.0.0.1, localhost)');
  }
  return { settings: out, errors };
}

class DesktopSettings {
  constructor(file) {
    this._file = file;
  }

  // 파일이 없거나 깨졌으면 기본값. 깨진 값만 기본값으로 돌리고 나머지는 살린다
  load() {
    let raw = {};
    try { raw = JSON.parse(fs.readFileSync(this._file, 'utf8')); } catch { raw = {}; }
    const keep = {};
    for (const [k, v] of Object.entries(raw && typeof raw === 'object' ? raw : {})) {
      if (!normalize({ [k]: v }).errors.length) keep[k] = v;
    }
    return normalize(keep).settings;
  }

  // 검증을 통과하면 임시 파일에 쓰고 바꿔 끼운다. 내용이 같으면 파일을 건드리지 않는다
  save(input) {
    const { settings, errors } = normalize({ ...this.load(), ...input });
    if (errors.length) return { ok: false, error: errors.join('; '), settings: this.load() };
    const text = `${JSON.stringify(settings, null, 2)}\n`;
    let current = null;
    try { current = fs.readFileSync(this._file, 'utf8'); } catch { current = null; }
    if (current !== text) {
      fs.mkdirSync(path.dirname(this._file), { recursive: true });
      const tmp = `${this._file}.${process.pid}.tmp`;
      fs.writeFileSync(tmp, text, 'utf8');
      fs.renameSync(tmp, this._file);
    }
    return { ok: true, settings };
  }
}

module.exports = { DEFAULTS, DesktopSettings, normalize, normalizeBackendUrl };
