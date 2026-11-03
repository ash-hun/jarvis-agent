// 데스크톱 앱(Electron) 연결부. window.jarvisDesktop 이 없으면(브라우저) 아무것도 하지 않는다.
import { logActivity } from './shell.js';
import { listenNow } from './voice-ui.js';
import { setView } from './view.js';

const bridge = window.jarvisDesktop;

if (bridge) {
  // 제목 표시줄을 숨긴 창이라 헤더가 창 끌기와 창 버튼 자리를 맡는다. 자리는 OS 마다 다르다
  document.body.classList.add('desktop-app', `desktop-${bridge.platform}`);
  // 전역 단축키: 셸이 창을 앞으로 가져온 뒤 보낸다. HUD 로 돌아와 듣기를 연다
  bridge.onHotkey(() => {
    setView('hud');
    listenNow();
  });
  logActivity(`desktop · ${bridge.platform} 셸에 연결됨`, 'ok');
}
