// 백엔드(jarvis-backend)가 응답하는지만 본다. 띄우는 일은 앱 밖(docker compose, Ion)의 몫이다. 의존은 주입한다.
const PROBE_TIMEOUT_MS = 3000;

class BackendProbe {
  constructor({ url, fetchImpl = fetch, timeoutMs = PROBE_TIMEOUT_MS }) {
    this._url = url;
    this._fetch = fetchImpl;
    this._timeoutMs = timeoutMs;
  }

  // 2xx 면 살아 있다. 연결 거부, 시간 초과, 5xx 는 모두 아직 없는 것으로 본다
  async alive() {
    try {
      const res = await this._fetch(`${this._url}/api/health`, { signal: AbortSignal.timeout(this._timeoutMs) });
      return res.status >= 200 && res.status < 300;
    } catch {
      return false;
    }
  }
}

module.exports = { BackendProbe, PROBE_TIMEOUT_MS };
