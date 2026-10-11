# 남은 작업

끝난 것은 지운다. 항목마다 왜 필요한지와 어디를 건드리는지를 적는다. 순서는 급한 것부터.

## 코드

- **피드백이 완전 일치 키워드만 읽는다.** `src/jarvis/ui/web/static/app/proactive.js` 의 `ponytail`. "응 그걸로 해줘" 같은 문장을 수락으로 읽으려면 서버 쪽 분류(사고 모델에 한 줄 물어보기)가 필요하다. 키워드 목록을 늘리는 것으로는 안 된다. 사고 모델이 e2b 로 짧은 분류는 1~2초라 이제 붙일 만하다. Full-voice 의 음성 승인 답(`app/approval.js` 의 `parseApprovalAnswer`)도 키워드라 같은 분류기를 쓰면 된다. 승인은 오인식 비용이 커서 분류기가 붙어도 거부 쪽 기울기는 유지한다.
- **사고 지연, 남은 레버.** 로컬(한 GPU)은 `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 첫 글자 12.8초, 총 29초, 💭 는 응답 뒤 약 10초. race(병렬)는 같은 GPU 를 나눠 써서 첫 글자 21초로 더 느렸다. 성찰 1회 약 7초(간격 127초). 남은 몫은 메인 모델의 프롬프트 처리 12초라 사고 쪽이 아니라 시스템 프롬프트와 도구 목록 크기를 봐야 한다. 클라우드 provider(anthropic + haiku 사고)에서는 race 가 맞는지 미측정.

## 화면

- **Focus 모드.** Default 와 Full-voice 는 헤더 세그먼트로 들어갔다(`app/mode.js`). Focus 는 🔔 를 세션 단위로 끄려면 ws `set_mode` 와 daemon 게이팅이 필요해 서버와 `docs/api-spec.md` 가 바뀐다. 카드 숨김(AGENDA, ACTIVITY, SYSTEM)은 클라이언트에서 `body[data-mode="focus"]` CSS 로 끝난다. 요구가 정해지면 한다.
- **오른쪽 여백(사용자 보고).** 헤더와 스테이지가 창보다 좁게 보인 스크린샷. headless 1000~2000px, DPR 1~2 에서 재현 안 됨. Claude 세션에 Chrome 확장이 없어 사용자 브라우저 값을 못 읽었다. HUD 탭 콘솔에 아래를 붙인 결과가 있어야 다음 단계.
  ```js
  ({ innerWidth, clientWidth: document.documentElement.clientWidth, stageRight: document.querySelector('.stage').getBoundingClientRect().right, headerRight: document.querySelector('header').getBoundingClientRect().right, dpr: devicePixelRatio, zoom: Math.round(outerWidth / innerWidth * 100) })
  ```
- **TUI 화면 명세 없음.** `docs/screen-spec.md` 는 Web HUD 만 다룬다. TUI 도 넣으려면 `src/jarvis/ui/tui/` 를 읽어 같은 형식으로.

## 문서·자산

- **문서 사이트 배포.** `website/docusaurus.config.ts` 는 `https://ash-hun.github.io/jarvis-agent/` 를 가리키지만 배포 워크플로가 없고 GitHub Pages 도 꺼져 있어 404 다. Pages 소스를 GitHub Actions 로 켜고, `website/` 를 `npm ci && npm run build` 해서 `website/build` 를 올리는 워크플로를 `.github/workflows/` 에 추가하면 된다.
- **모션그래픽 mp4 판.** `assets/hud-motion/` 의 `ponytail` 자리(그레인, 배경 드리프트, 카드 숨쉬기)는 GIF 크기 때문에 껐다. mp4 를 올릴 곳이 생기면 되살린다. 녹화 소재(`public/*.mp4`)는 gitignore 라 `capture_video.py` 로 다시 찍는다.
- **e2e 자동화는 시나리오 2, 3 만.** `scripts/e2e/hud_flow.py` 는 스크립트 프로바이더로 승인 기억과 절차 학습을 돈다. 시나리오 1(성찰 → 🔔 → 피드백)은 수동(`hud-scenario.md`). 스크립트 프로바이더에 성찰 프레임을 넣으면 자동화할 수 있다.
