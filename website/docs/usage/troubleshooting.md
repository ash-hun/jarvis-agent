---
sidebar_position: 7
title: 문제 해결
---

# 문제 해결

## 🔔 가 안 뜬다

백엔드 로그에 이유가 있다.

```text
[Thought] proactive silent: cooldown
[Thought] proactive silent: confidence 0.42 < 0.6
[Thought] proactive silent: empty utterance
[Thought] proactive silent: decision=silent
```

- `cooldown`: 마지막 발화 뒤 300초가 안 지났다
- `confidence`: 사고 프레임의 확신도가 임계치 미만. 피드백 학습으로 임계치가 올라갔을 수도 있다
- `empty utterance`: 모델이 건넬 말을 안 채웠다. 사고 템플릿에 `utterance` 키가 있는지 본다
- 로그가 아예 없으면 daemon 이 꺼져 있거나(`JARVIS_PROACTIVE__DAEMON_ENABLED`), 성찰 프레임이 깨지고 있다

## 사고 프레임이 깨진다

```text
[Thought] reflection frame unparsable (len=1269): ...
[Thought] frame invalid: decision: Input should be 'act', 'ask' or 'silent'
[Thought] dropped invalid proactive_actions: ...
```

모델이 JSON 스키마를 못 지킨 것이다. 마지막 줄은 행동 후보만 버리고 프레임은 살린 경우라 괜찮다. 앞의 둘이 반복되면 사고 모델을 바꾼다. Ollama 는 스키마를 `format` 으로 강제하는데, 모델이 structured output 을 지원하지 않으면 `call failed ... 501` 로 사고가 통째로 생략된다.

## 응답이 느리다

로컬 한 GPU 에서 사고와 메인을 같이 돌리면 서로 느려진다. `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 두면 응답이 먼저 나오고 사고는 뒤에 돈다. 성찰 자체가 느리면 `HISTORY_TURNS`, `HISTORY_CHARS` 를 줄이거나 사고 모델을 작은 것으로 바꾼다. 남은 지연은 메인 모델의 프롬프트 처리(시스템 프롬프트, 도구 목록)다.

## 설정이 안 먹는다

- 접두사와 구분자: `JARVIS_THOUGHT__MODEL` 처럼 `__` 두 개
- Docker 는 compose 가 `.env` 를 읽어 컨테이너 환경에 넣는다. `.env` 를 고쳤으면 `docker compose up -d jarvis-backend` 로 컨테이너를 다시 만들어야 한다. `restart` 는 환경을 안 바꾼다
- 중첩 설정은 `PATH` 같은 접두사 없는 환경변수를 읽지 않는다. 읽는 것처럼 보이면 버그다

## 승인 모달

- 탭을 여럿 열어도 같은 세션이면 모두 모달을 받고, 하나가 답하면 나머지는 닫힌다
- 120초 안에 답이 없으면 거부로 처리되고 도구 결과에 `denied` 가 온다
- `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다

## 화면이 옛날 것이다

정적 파일은 네트워크 우선이라 새로고침이면 반영된다. 그래도 옛 것이 보이면 브라우저의 서비스 워커를 지우고(개발자 도구 Application 탭) 다시 연다. nginx 와 백엔드 모두 `Cache-Control: no-cache` 를 붙인다.

## 세션이 안 보인다

SESSIONS 카드는 프로세스가 띄운 세션만 보여준다. 저장소에만 있는 세션은 `jarvis --list-sessions` 또는 `/sessions` 로 본다. 지우려면 카드의 ✕ 또는 `DELETE /api/sessions/{id}`.

## 음성

- 브라우저 STT 는 Chrome 계열에서 된다. 미지원이면 구체를 클릭했을 때 SYS 에러가 한 줄 뜬다
- 서버 STT, TTS 는 `uv sync --extra voice` 가 필요하다. TUI 는 추가로 시스템 오디오 도구(재생 afplay, paplay, aplay, ffplay 중 하나, 녹음 sox 또는 arecord)가 있어야 한다
