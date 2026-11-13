const test = require('node:test');
const assert = require('node:assert/strict');

const { BackendProbe } = require('../backend_probe');

test('alive is true only for a 2xx health response', async () => {
  const seen = [];
  const probe = new BackendProbe({ url: 'http://127.0.0.1:7777', fetchImpl: async (url) => { seen.push(url); return { status: 200 }; } });
  assert.equal(await probe.alive(), true);
  assert.deepEqual(seen, ['http://127.0.0.1:7777/api/health']);
  assert.equal(await new BackendProbe({ url: 'http://x', fetchImpl: async () => ({ status: 502 }) }).alive(), false);
});

test('alive is false when the request throws or times out', async () => {
  assert.equal(await new BackendProbe({ url: 'http://x', fetchImpl: async () => { throw new Error('refused'); } }).alive(), false);
  const slow = new BackendProbe({
    url: 'http://x', timeoutMs: 10,
    fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => { signal.addEventListener('abort', () => reject(signal.reason)); }),
  });
  assert.equal(await slow.alive(), false);
});
