---
sidebar_position: 5
title: FAQ
---

# FAQ

이 페이지는 자주 겪는 증상마다 원인과 확인할 곳을 모은다.

## 먼저 건네는 말이 오지 않을 때

JARVIS 는 침묵할 때마다 그 이유를 백엔드 로그에 남긴다. 아래 중 어느 것인지 먼저 확인한다.

```text
[Thought] proactive silent: cooldown
[Thought] proactive silent: confidence 0.42 < 0.6
[Thought] proactive silent: empty utterance
[Thought] proactive silent: decision=silent
```

- `cooldown`: 마지막 발화 뒤 300초가 지나지 않았다
- `confidence`: 사고 프레임의 확신도가 임계치보다 낮다. 피드백 학습으로 임계치가 올라갔을 수도 있다
- `empty utterance`: 모델이 건넬 말을 채우지 않았다. 사고 템플릿에 `utterance` 키가 있는지 확인한다
- 로그가 아예 없으면 daemon 이 꺼져 있거나(`JARVIS_PROACTIVE__DAEMON_ENABLED`) 성찰 프레임이 깨지고 있는 것이다

## 사고 프레임이 깨진다

```text
[Thought] reflection frame unparsable (len=1269): ...
[Thought] frame invalid: decision: Input should be 'act', 'ask' or 'silent'
[Thought] dropped invalid proactive_actions: ...
```

사고 모델이 JSON 스키마를 지키지 못한 것이다. 마지막 줄은 행동 후보만 버리고 프레임은 살린 경우라서 괜찮다. 앞의 두 줄이 반복되면 사고 모델을 바꾼다. Ollama 는 스키마를 `format` 으로 강제하는데, 모델이 structured output 을 지원하지 않으면 `call failed ... 501` 이 찍히고 사고가 통째로 생략된다.

## 응답이 느리다

로컬 GPU 한 장에서 사고와 메인을 같이 돌리면 서로 느려진다. `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 두면 응답이 먼저 나오고 사고는 뒤에 돈다. 성찰 자체가 느리면 `HISTORY_TURNS`, `HISTORY_CHARS` 를 줄이거나 사고 모델을 작은 것으로 바꾼다. 그래도 남는 지연은 메인 모델이 프롬프트(시스템 프롬프트, 도구 목록)를 처리하는 시간이다.

## 설정이 안 먹는다

- 접두사와 구분자를 확인한다. `JARVIS_THOUGHT__MODEL` 처럼 밑줄 두 개(`__`)로 이어야 한다
- Docker 에서는 compose 가 `.env` 를 읽어 컨테이너 환경에 넣는다. `.env` 를 고쳤으면 `docker compose up -d jarvis-backend` 로 컨테이너를 다시 만든다. `restart` 로는 환경이 바뀌지 않는다
- 중첩 설정은 `PATH` 처럼 접두사가 없는 환경변수를 읽지 않는다. 읽는 것처럼 보이면 버그다

## 승인 모달

- 같은 세션을 여러 탭에서 열었으면 모든 탭이 모달을 받고, 한 탭이 답하면 나머지 모달은 닫힌다
- 120초 안에 답이 없으면 거부로 처리되고, 도구 결과에 `denied` 가 온다
- `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다

## 화면이 옛날 것이다

정적 파일은 네트워크 우선으로 받으므로 새로고침하면 반영된다. 그래도 옛 화면이 보이면 브라우저 개발자 도구의 Application 탭에서 서비스 워커를 지우고 다시 연다. nginx 와 백엔드는 모두 `Cache-Control: no-cache` 를 붙인다.

## 세션이 안 보인다

SESSIONS 카드는 지금 프로세스가 띄운 세션만 보여준다. 저장소에만 있는 세션은 `jarvis --list-sessions` 나 `/sessions` 로 본다. 세션을 지우려면 카드의 ✕ 를 누르거나 `DELETE /api/sessions/{id}` 를 호출한다.

## 청약 공고 조회

- **`LH 게시판 조회 실패` 나 `SH 게시판 조회 실패`**: 사이트에 닿지 못했거나 오류 응답을 받은 것이다. 백엔드 컨테이너에서 `curl -I https://apply.lh.or.kr` 로 연결을 확인한다
- **`예상한 목록 표를 주지 않았다`, `공고 상세를 읽지 못했다`**: 사이트 화면 구조가 바뀌었거나, 점검 화면이나 접속 대기(NetFunnel) 화면이 뜬 것이다. 도구는 공고를 지어내지 않고 이 오류를 돌려준다. 계속되면 `core/tools/housing/` 의 파싱 정규식을 실제 페이지에 맞춘다
- **JARVIS 에게는 도구가 없다**: 청약 도구는 KAREN 전용이므로 JARVIS 세션의 TOOLS 에 보이지 않는 것이 맞다. 다른 에이전트에게 주려면 그 정의 파일의 `tools` 에 이름을 적는다
- **도구를 부르지 않고 지난 공고로 답한다**: 작은 모델이 KAREN 의 장기 기억(지난 대화 요약)을 꺼내 답한 경우다. 프롬프트는 매번 도구를 먼저 부르게 하지만, 그래도 계속되면 "lh_notice 로 다시 조회해" 처럼 도구 이름을 말하거나 더 큰 모델을 쓴다
- **예산 추천에 "금액을 찾지 못한 공고" 가 많다**: 매입임대, 전세임대는 집마다 금액이 달라서 금액이 주택목록 엑셀에만 있다. 임대 공고는 공고문 PDF 의 임대조건 표를 읽는데, 표가 표준 꼴이 아니면 읽지 못한다. 결과의 링크로 첨부를 직접 확인한다
- **예산 추천의 가장 싼 주택형이 내 자격과 다르다**: 주택형 이름에 붙은 공급대상(수급자, 청년, 「가」군 등)이 신청 자격이다. 도구는 조건에 맞는 주택형 중 월 부담이 가장 작은 것을 고른다
- **상환액이 이상하다**: 답에 `housing_loan` 결과의 숫자가 그대로 있는지 본다. 모델이 손으로 계산한 값이면 틀릴 수 있다. HUD 의 도구 실행 줄에서 `housing_loan` 이 불렸는지 확인한다

## 작업 패턴

- **"기억하겠습니다" 라고 했는데 다음에 안 따른다**: `/patterns` 로 그 에이전트에 작업 패턴이 저장됐는지 본다. 없으면 모델이 저장 도구를 부르지 않은 것이다. "remember_task_pattern 으로 저장해" 라고 말하면 확실히 저장된다
- **다른 에이전트가 모른다**: 작업 패턴은 저장한 에이전트만 쓴다. 다른 에이전트에도 필요하면 그 에이전트 세션에서 같은 방식을 알려 준다
- **엉뚱한 요청에 패턴이 붙는다**: 키워드가 너무 흔한 말이라서 그렇다. `/patterns forget <이름>` 으로 지우고 더 좁은 키워드로 다시 알려 준다

## 음성

- 브라우저 STT 는 Chrome 계열에서 동작한다. 지원하지 않는 브라우저에서는 구체를 클릭했을 때 SYS 에러가 한 줄 뜬다
- 서버 STT, TTS 를 쓰려면 `uv sync --extra voice` 로 설치해야 한다. TUI 는 시스템 오디오 도구(재생은 afplay, paplay, aplay, ffplay 중 하나, 녹음은 sox 나 arecord)도 있어야 한다
