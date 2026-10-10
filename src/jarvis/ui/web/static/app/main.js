// HUD 진입점 — 모듈을 잇고 기본 세션에 붙는다.
import { showQuote, setupCollapse } from './shell.js';
import { scrollToEnd } from './messages.js';
import { setInputEnabled } from './composer.js';
import { connect } from './session.js';
import { handleMessage } from './events.js';

setupCollapse('chat-toggle', 'chat-collapsed', 'hud.chatCollapsed', scrollToEnd);
setupCollapse('sessions-toggle', 'sessions-collapsed', 'hud.sessionsCollapsed');

// e2e 가 서버 이벤트를 흉내 낼 때 쓴다. 앱 코드는 이 핸들을 쓰지 않는다.
window.jarvisDebug = { handleMessage };

showQuote();
setInputEnabled(false);
connect('default');
