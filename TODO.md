# 남은 작업

끝난 것은 지운다. 항목마다 왜 필요한지와 어디를 건드리는지를 적는다. 순서는 급한 것부터.

## 코드

- **피드백이 완전 일치 키워드만 읽는다.** `static/app/proactive.js` 의 `ponytail`. "응 그걸로 해줘" 같은 문장을 수락으로 읽으려면 서버 쪽 분류(사고 모델에 한 줄 물어보기)가 필요하다. 키워드 목록을 늘리는 것으로는 안 된다.
- **성찰 지연, 남은 레버.** 사고 모델 gemma4:e2b-it-qat + Ollama `format` 스키마 강제로 성찰 1회 약 8초(기록 간격 128초), 요청 사고 💭 10~14초. 요청 사고가 메인 응답 앞에 붙으므로 체감 지연의 다음 레버는 성찰 프롬프트 다이어트(history 12턴 × 400자 + 회상 5건)와 요청 사고 병렬화. `format` 을 못 받는 모델(qwen3.5 계열, 501)은 사고가 통째로 생략되고 로그에 `call failed` 만 남는다.

## 화면

- **오른쪽 여백(사용자 보고).** 헤더와 스테이지가 창보다 좁게 보인 스크린샷. headless 1000~2000px, DPR 1~2 에서 재현 안 됨. 브라우저 콘솔에서 `innerWidth`, `.stage` 의 `getBoundingClientRect().right`, `document.documentElement.clientWidth` 값을 받아야 다음 단계.
- **세션 삭제 UI 없음.** `/cleanup` 과 DB 직접 삭제뿐. API(`DELETE /api/sessions/{id}`)와 SESSIONS 카드의 ✕ 가 필요하면 `docs/api-spec.md`, `docs/screen-spec.md` 를 같이 갱신.
- **TUI 화면 명세 없음.** `docs/screen-spec.md` 는 Web HUD 만 다룬다. TUI 도 넣으려면 `src/jarvis/ui/tui/` 를 읽어 같은 형식으로.

## 문서·자산

- **모션그래픽 mp4 판.** `assets/hud-motion/` 의 `ponytail` 자리(그레인, 배경 드리프트, 카드 숨쉬기)는 GIF 크기 때문에 껐다. mp4 를 올릴 곳이 생기면 되살린다. 녹화 소재(`public/*.mp4`)는 gitignore 라 `capture_video.py` 로 다시 찍는다.
- **e2e 자동화는 시나리오 2, 3 만.** `scripts/e2e/hud_flow.py` 는 스크립트 프로바이더로 승인 기억과 절차 학습을 돈다. 시나리오 1(성찰 → 🔔 → 피드백)은 수동(`hud-scenario.md`). 스크립트 프로바이더에 성찰 프레임을 넣으면 자동화할 수 있다.
