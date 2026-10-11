# 남은 작업

끝난 것은 지운다. 항목마다 왜 필요한지와 어디를 건드리는지를 적는다. 순서는 급한 것부터.

## 코드

- **open loop 판정이 글자 겹침이다.** `src/jarvis/agent_layer/openloop/types.py` 의 `ponytail` 두 곳. 같은 약속 판정(`same_loop`)은 bigram Jaccard 0.4 라 단어를 통째로 바꾼 중복("참석자 목록 확정" 과 "참석자들의 최종 리스트 확정", 0.21)이 쌓인다. 저장 조건(`grounded`)은 입력과 겹침 20% 라 통째로 바꿔 말한 약속이 버려진다. 앞은 임베딩 유사도(메모리 계층에 임베딩이 있으면 그걸 쓴다), 뒤는 사고가 약속마다 근거 문장을 같이 내게 해서 근거 문장과 입력을 비교한다. 측정 기준과 나머지 한계는 docs 의 `features/agenda.md` "한계" 표.
- **사고 지연, 남은 레버.** 로컬(한 GPU)은 `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 첫 글자 12.8초, 총 29초, 💭 는 응답 뒤 약 10초. race(병렬)는 같은 GPU 를 나눠 써서 첫 글자 21초로 더 느렸다. 성찰 1회 약 7초(간격 127초). 남은 몫은 메인 모델의 프롬프트 처리 12초라 사고 쪽이 아니라 시스템 프롬프트와 도구 목록 크기를 봐야 한다. 클라우드 provider(anthropic + haiku 사고)에서는 race 가 맞는지 미측정.

## 화면

- **에어팟에서 승인 되읽기 확인(사용자).** Full-voice 에서 "허용" 뒤 "허용으로 들었습니다." 가 에어팟에서 안 들렸다. #79 로 인식이 닫힌 뒤 0.6초 쉬고, 1.5초 안에 시작하지 않으면 한 번 다시 읽게 했지만 실기기 확인 전이다. Mac 내장 스피커에서는 원래도 들렸다. 안 들리면 브라우저 콘솔의 `[voice] tts start / error / did not start` 줄이 다음 단서다(`voice.js`).
- **Focus 모드.** Default 와 Full-voice 는 헤더 세그먼트로 들어갔다(`app/mode.js`). Focus 는 🔔 를 세션 단위로 끄려면 ws `set_mode` 와 daemon 게이팅이 필요해 서버와 `docs/api-spec.md` 가 바뀐다. 카드 숨김(AGENDA, ACTIVITY, SYSTEM)은 클라이언트에서 `body[data-mode="focus"]` CSS 로 끝난다. 요구가 정해지면 한다.
- **오른쪽 여백(사용자 보고).** 헤더와 스테이지가 창보다 좁게 보인 스크린샷. headless 1000~2000px, DPR 1~2 에서 재현 안 됨. Claude 세션에 Chrome 확장이 없어 사용자 브라우저 값을 못 읽었다. HUD 탭 콘솔에 아래를 붙인 결과가 있어야 다음 단계.
  ```js
  ({ innerWidth, clientWidth: document.documentElement.clientWidth, stageRight: document.querySelector('.stage').getBoundingClientRect().right, headerRight: document.querySelector('header').getBoundingClientRect().right, dpr: devicePixelRatio, zoom: Math.round(outerWidth / innerWidth * 100) })
  ```
- **TUI 화면 명세 없음.** `docs/screen-spec.md` 는 Web HUD 만 다룬다. TUI 도 넣으려면 `src/jarvis/ui/tui/` 를 읽어 같은 형식으로.

## 문서·자산

- **모션그래픽 mp4 판.** `assets/hud-motion/` 의 `ponytail` 자리(그레인, 배경 드리프트, 카드 숨쉬기)는 GIF 크기 때문에 껐다. mp4 를 올릴 곳이 생기면 되살린다. 녹화 소재(`public/*.mp4`)는 gitignore 라 `capture_video.py` 로 다시 찍는다.
- **e2e 자동화는 시나리오 2, 3 만.** `scripts/e2e/hud_flow.py` 는 스크립트 프로바이더로 승인 기억과 절차 학습을 돈다. 시나리오 1(성찰 → 🔔 → 피드백)은 수동(`hud-scenario.md`). 스크립트 프로바이더에 성찰 프레임을 넣으면 자동화할 수 있다.
