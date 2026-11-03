const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { DEFAULTS, DesktopSettings, normalize, normalizeBackendUrl } = require('../desktop_settings');

function tmpFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'jarvis-desktop-')), 'sub', 'settings.json');
}

test('normalizeBackendUrl keeps only loopback http origins', () => {
  assert.equal(normalizeBackendUrl('http://127.0.0.1:7777/path?q=1'), 'http://127.0.0.1:7777');
  assert.equal(normalizeBackendUrl('http://localhost:8000'), 'http://localhost:8000');
  assert.equal(normalizeBackendUrl('http://evil.example:7777'), null);
  assert.equal(normalizeBackendUrl('file:///etc/passwd'), null);
});

test('normalize drops unknown keys and reports bad values', () => {
  const { settings, errors } = normalize({ hotkey: 'Cmd+J; rm', autoLaunch: 'yes', extra: 1 });
  assert.deepEqual(settings, DEFAULTS);
  assert.equal(errors.length, 2);
});

test('save writes once, is idempotent, and rejects bad input without writing', () => {
  const file = tmpFile();
  const store = new DesktopSettings(file);

  assert.deepEqual(store.load(), DEFAULTS);
  assert.equal(store.save({ autoLaunch: true }).ok, true);
  const first = fs.statSync(file).mtimeMs;
  const text = fs.readFileSync(file, 'utf8');
  assert.equal(store.save({ autoLaunch: true }).ok, true);
  assert.equal(fs.readFileSync(file, 'utf8'), text);
  assert.equal(fs.statSync(file).mtimeMs, first);
  const bad = store.save({ backendUrl: 'http://10.0.0.5:7777' });
  assert.equal(bad.ok, false);
  assert.equal(store.load().autoLaunch, true);
  assert.equal(store.load().backendUrl, DEFAULTS.backendUrl);
});

test('load keeps valid keys from a partly broken file', () => {
  const file = tmpFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ autoLaunch: true, hotkey: '!!' }));
  assert.deepEqual(new DesktopSettings(file).load(), { ...DEFAULTS, autoLaunch: true });
  fs.writeFileSync(file, '{not json');
  assert.deepEqual(new DesktopSettings(file).load(), DEFAULTS);
});
