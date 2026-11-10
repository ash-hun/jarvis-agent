# 남은 작업

끝난 것은 지운다. 항목마다 왜 필요한지와 어디를 건드리는지를 적는다. 순서는 급한 것부터.

## 코드

- **사고 지연, 남은 레버.** 12.8초(첫 글자), 프롬프트 처리 12초는 #69 무렵 로컬 GPU 하나에서 잰 값이고, 지금 운영은 OpenAI(`gpt-4o-mini`, 스케줄 작업은 `gpt-4o`)다. 시스템 프롬프트 749자와 도구 15개 8,570자(합쳐 약 3K 토큰)에 비해 실제 호출 입력은 6,500~8,500 토큰이라 나머지는 메모리 블록과 대화 창이다. 루프가 호출마다 `[Loop] llm call` 로그(첫 출력 초, 부분별 글자 수, `cache_read`)를 남기므로, 운영 로그를 며칠 모아 가장 큰 동적 블록과 캐시 적중률을 본 뒤 고정 부분을 앞에 두거나 큰 블록을 줄인다. 클라우드 provider(anthropic + haiku 사고)에서 race 가 맞는지도 같은 로그로 잰다.

## 화면

- **에어팟에서 승인 되읽기 확인(사용자).** Full-voice 에서 "허용" 뒤 "허용으로 들었습니다." 가 에어팟에서 안 들렸다. #79 로 인식이 닫힌 뒤 0.6초 쉬고, 1.5초 안에 시작하지 않으면 한 번 다시 읽게 했지만 실기기 확인 전이다. Mac 내장 스피커에서는 원래도 들렸다. 안 들리면 브라우저 콘솔의 `[voice] tts start / error / did not start` 줄이 다음 단서다(`voice.js`).
- **오른쪽 여백(사용자 보고).** 헤더와 스테이지가 창보다 좁게 보인 스크린샷. headless 1000~2000px, DPR 1~2 에서 재현 안 됨. Claude 세션에 Chrome 확장이 없어 사용자 브라우저 값을 못 읽었다. HUD 탭 콘솔에 아래를 붙인 결과가 있어야 다음 단계.
  ```js
  ({ innerWidth, clientWidth: document.documentElement.clientWidth, stageRight: document.querySelector('.stage').getBoundingClientRect().right, headerRight: document.querySelector('header').getBoundingClientRect().right, dpr: devicePixelRatio, zoom: Math.round(outerWidth / innerWidth * 100) })
  ```
- **데스크톱 앱 음성 확인.** Electron 에서 브라우저 인식이 `network` 로 끝나 서버 STT 로 넘어가는 경로는 코드로만 만들었다. 실제 마이크로 말해 보고 whisper 정확도와 지연을 잰 뒤 모델 크기(`JARVIS_VOICE__WHISPER_MODEL_SIZE`)를 정한다.
- **데스크톱 앱 번들.** 지금은 저장소 안에서 `npm start` 로만 띄운다. 매일 쓰게 되면 electron-builder 로 .app 을 만들고 서명과 공증을 붙인다.

## 문서·자산

- **모션그래픽 mp4 판.** `assets/hud-motion/` 의 `ponytail` 자리(그레인, 배경 드리프트, 카드 숨쉬기)는 GIF 크기 때문에 껐다. mp4 를 올릴 곳이 생기면 되살린다. 녹화 소재(`public/*.mp4`)는 gitignore 라 `capture_video.py` 로 다시 찍는다.
- **e2e 자동화는 시나리오 2, 3 만.** `scripts/e2e/hud_flow.py` 는 스크립트 프로바이더로 승인 기억과 절차 학습을 돈다. 시나리오 1(성찰 → 🔔 → 피드백)은 수동(`hud-scenario.md`). 스크립트 프로바이더에 성찰 프레임을 넣으면 자동화할 수 있다.
