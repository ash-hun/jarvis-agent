// HUD 진입점 — 모듈을 잇고 기본 세션에 붙는다.
import { showQuote, setupCollapse } from './shell.js';
import { scrollToEnd } from './messages.js';
import { setInputEnabled } from './composer.js';
import { connect } from './session.js';
import { handleMessage } from './events.js';
import { restoreView } from './view.js';
import { apiFetch } from './api.js';
import './workflow.js';
import './settings.js';
import './desktop.js';

setupCollapse('chat-toggle', 'chat-collapsed', 'hud.chatCollapsed', scrollToEnd);
setupCollapse('sessions-toggle', 'sessions-collapsed', 'hud.sessionsCollapsed');

// e2e 가 서버 이벤트를 흉내 낼 때 쓴다. 앱 코드는 이 핸들을 쓰지 않는다.
window.jarvisDebug = { handleMessage };

showQuote();
setInputEnabled(false);
connect('default');
restoreView();

// 버전은 pyproject.toml 한 곳에만 있다. 백엔드가 알려 준 값을 헤더에 보인다
apiFetch('/api/health')
  .then((r) => (r.ok ? r.json() : null))
  .then((body) => {
    if (body?.version) document.getElementById('app-version').textContent = `/ v${body.version}`;
  })
  .catch(() => {});
