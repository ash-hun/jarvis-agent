// 백엔드(jarvis-backend 컨테이너)가 떠 있는지 보고, 없으면 docker compose 로 띄우거나 다시 띄운다. 의존은 모두 주입한다.
const PROBE_TIMEOUT_MS = 2000;
const WAIT_TIMEOUT_MS = 120_000;
const POLL_MS = 1000;
const COMPOSE_UP = ['compose', '--profile', 'web', 'up', '-d'];
const COMPOSE_RESTART = ['compose', 'restart', 'jarvis-backend'];

class BackendLauncher {
  // run(cmd, args, opts) 는 셸 없이 실행하고 { code, stderr } 를 준다. fetch 와 sleep 은 시험에서 바꾼다
  constructor({ url, composeDir, run, fetchImpl = fetch, sleep, now = Date.now, waitTimeoutMs = WAIT_TIMEOUT_MS }) {
    this._url = url;
    this._composeDir = composeDir;
    this._run = run;
    this._fetch = fetchImpl;
    this._sleep = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
    this._now = now;
    this._waitTimeoutMs = waitTimeoutMs;
  }

  // 어떤 HTTP 응답이든 오면 떠 있다. 키를 요구하는 백엔드는 401 을 주지만 살아 있다
  async probe() {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    try {
      await this._fetch(`${this._url}/api/health`, { signal: ctrl.signal });
      return true;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async waitUntilUp() {
    const deadline = this._now() + this._waitTimeoutMs;
    while (this._now() < deadline) {
      if (await this.probe()) return true;
      await this._sleep(POLL_MS);
    }
    return false;
  }

  // 이미 떠 있으면 아무것도 하지 않는다. compose up -d 도 멱등이라 두 번 불러도 컨테이너는 하나다
  async ensure({ start }) {
    if (await this.probe()) return { ok: true, started: false };
    if (!start) return { ok: false, error: `백엔드(${this._url})가 응답하지 않습니다. docker compose --profile web up -d 로 띄우세요.` };
    const result = await this._run('docker', COMPOSE_UP, { cwd: this._composeDir });
    if (result.code !== 0) return { ok: false, error: `docker compose up 실패: ${result.stderr.trim().slice(-400)}` };
    return (await this.waitUntilUp())
      ? { ok: true, started: true }
      : { ok: false, error: '백엔드가 제한 시간 안에 뜨지 않았습니다. docker compose logs jarvis-backend 를 보세요.' };
  }

  async restart() {
    const result = await this._run('docker', COMPOSE_RESTART, { cwd: this._composeDir });
    if (result.code !== 0) return { ok: false, error: `docker compose restart 실패: ${result.stderr.trim().slice(-400)}` };
    // restart 직후 잠깐은 옛 프로세스가 아직 응답할 수 있다. 한 번 쉬고 본다
    await this._sleep(POLL_MS);
    return (await this.waitUntilUp()) ? { ok: true } : { ok: false, error: '재시작 후 백엔드가 응답하지 않습니다.' };
  }
}

module.exports = { BackendLauncher, COMPOSE_UP, COMPOSE_RESTART };
