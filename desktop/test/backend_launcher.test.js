const test = require('node:test');
const assert = require('node:assert/strict');

const { BackendLauncher, COMPOSE_UP, COMPOSE_RESTART } = require('../backend_launcher');

function fakeClock() {
  let t = 0;
  return { now: () => t, sleep: async (ms) => { t += ms; } };
}

function launcher({ upAfter = 0, code = 0 } = {}) {
  const calls = [];
  let probes = 0;
  const clock = fakeClock();
  const l = new BackendLauncher({
    url: 'http://127.0.0.1:7777',
    composeDir: '/repo',
    run: async (cmd, args, opts) => { calls.push([cmd, args, opts.cwd]); return { code, stderr: code ? 'boom' : '' }; },
    fetchImpl: async () => { probes += 1; if (probes <= upAfter) throw new Error('refused'); return { status: 200 }; },
    sleep: clock.sleep,
    now: clock.now,
    waitTimeoutMs: 5000,
  });
  return { l, calls };
}

test('ensure does nothing when backend already answers', async () => {
  const { l, calls } = launcher();
  assert.deepEqual(await l.ensure({ start: true }), { ok: true, started: false });
  assert.equal(calls.length, 0);
});

test('ensure starts compose once and waits until it answers', async () => {
  const { l, calls } = launcher({ upAfter: 3 });
  assert.deepEqual(await l.ensure({ start: true }), { ok: true, started: true });
  assert.deepEqual(calls, [['docker', COMPOSE_UP, '/repo']]);
});

test('ensure reports instead of starting when start is off, and reports compose failure', async () => {
  assert.equal((await launcher({ upAfter: 99 }).l.ensure({ start: false })).ok, false);
  const failed = await launcher({ upAfter: 99, code: 1 }).l.ensure({ start: true });
  assert.equal(failed.ok, false);
  assert.match(failed.error, /boom/);
});

test('restart times out when backend never comes back', async () => {
  const { l, calls } = launcher({ upAfter: 999 });
  assert.equal((await l.restart()).ok, false);
  assert.deepEqual(calls, [['docker', COMPOSE_RESTART, '/repo']]);
});
