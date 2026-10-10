// REST 호출과 접근 키. 서버에 JARVIS_SECURITY__API_KEYS 가 설정돼 있으면 /ws 와 /api 가 키를 요구한다.
// 키는 이 브라우저에만 저장되는 편의 값이라 localStorage 에 둔다(없으면 서버가 4401 로 끊고 다시 묻는다).
const TOKEN_KEY = 'jarvis_token';

export function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* 무시 */ } }

export function apiFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  return fetch(path, { ...opts, headers });
}

export function askForToken() {
  const t = window.prompt('접근 키를 입력하세요 (JARVIS_SECURITY__API_KEYS)');
  if (!t || !t.trim()) return false;
  setToken(t.trim());
  return true;
}
