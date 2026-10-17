// 미리 녹음한 읽기 문구 — 서버가 connected 로 알려 준 이름만 받아 두고, 처음 쓸 때 wav 를 받아 둔다.
import { apiFetch } from './api.js';

let _names = new Set();
const _wavs = new Map();  // 이름 → Promise<ArrayBuffer | null>

export function setPhrases(names) { _names = new Set(names || []); }
export function hasPhrase(name) { return !!name && _names.has(name); }

export function phraseWav(name) {
  if (!_wavs.has(name)) {
    const wav = apiFetch(`/api/voice/phrases/${encodeURIComponent(name)}`)
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .catch(() => null)
      .then((buf) => {
        if (!buf) _wavs.delete(name);  // 실패는 담아 두지 않는다. 다음에 다시 받는다
        return buf;
      });
    _wavs.set(name, wav);
  }
  return _wavs.get(name);
}
