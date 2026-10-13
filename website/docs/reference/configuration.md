---
sidebar_position: 1
title: 설정
---

# 설정

이 페이지는 JARVIS 가 읽는 설정을 영역별로 모은다. 모든 설정은 환경변수로 준다.

이름은 `JARVIS_` 접두사로 시작하고, 중첩 단계는 `__` 로 구분한다. JARVIS 는 `.env` 파일을 읽되, 같은 이름의 환경변수가 있으면 환경변수를 쓴다.

:::note

설정의 정본은 레포의 `.env.example` 과 `src/jarvis/config.py` 다.

:::

## LLM

```bash
JARVIS_LLM__PROVIDER=anthropic        # anthropic | openai | google | ollama | vllm
JARVIS_LLM__MODEL=claude-sonnet-4-5
JARVIS_LLM__API_KEY=
JARVIS_LLM__BASE_URL=                 # Ollama, vLLM 전용
JARVIS_LLM__MAX_TOKENS=4096
JARVIS_LLM__TEMPERATURE=0.7
```

## 내적 사고와 proactive

```bash
JARVIS_THOUGHT__ENABLED=true
JARVIS_THOUGHT__MODEL=                     # 비우면 메인 모델. 사고 전용 모델을 따로 둘 때
JARVIS_THOUGHT__PROVIDER=                  # 비우면 메인 provider 상속(api_key, base_url 도 같이)
JARVIS_THOUGHT__REQUEST_TIMING=race        # before | race | after
JARVIS_THOUGHT__WAIT_SEC=3.0               # race 에서 사고를 기다리는 상한
JARVIS_THOUGHT__HISTORY_TURNS=8            # 사고 프롬프트에 넣는 최근 턴 수
JARVIS_THOUGHT__HISTORY_CHARS=240          # 턴당 글자 상한
JARVIS_THOUGHT__PROMPT_PATH=~/.jarvis/inner_thought.md
JARVIS_THOUGHT__REFLECTION_PROMPT_PATH=~/.jarvis/inner_thought_reflection.md
JARVIS_THOUGHT__LOG_SINKS=["ltm"]          # ltm | stm
JARVIS_THOUGHT__COMPOSER=default           # default | interpretation_only

JARVIS_PROACTIVE__ENABLED=true
JARVIS_PROACTIVE__CONFIDENCE_THRESHOLD=0.6
JARVIS_PROACTIVE__COOLDOWN_SEC=300
JARVIS_PROACTIVE__IGNORE_AFTER_SEC=600  # 🔔 뒤 답이 없으면 이만큼 지나 약한 무시로 학습
JARVIS_PROACTIVE__DAEMON_ENABLED=true
JARVIS_PROACTIVE__DAEMON_TRIGGER=interval  # interval | idle | both
JARVIS_PROACTIVE__DAEMON_INTERVAL_SEC=120
JARVIS_PROACTIVE__DAEMON_IDLE_SEC=180
```

### 사고 모델 고르기

사고 프레임은 JSON 이다. 사고 모델이 형식을 지키지 못하면 프레임이 버려지고, 먼저 건네는 말은 끝내 뜨지 않는다.

- 메인 모델이 클라우드에 있으면 사고는 더 싼 모델(`claude-haiku-4-5` 등)로 분리한다
- 로컬 Ollama 에서는 `gemma4:e2b-it-qat` 로 검증했다. Ollama 프로바이더는 사고 호출에 JSON 스키마를 `format` 으로 강제한다. 0.8b 급 모델은 스키마를 줘도 형식을 지키지 못했다. qwen3.5 계열은 Ollama 0.40 에서 `format` 자체가 501 을 돌려주므로 사고가 통째로 생략된다
- `~/.jarvis/inner_thought.md` 로 템플릿을 직접 쓸 때도 `utterance` 키는 있어야 한다. 없으면 daemon 이 항상 침묵한다

### 요청 사고 시점

`JARVIS_THOUGHT__REQUEST_TIMING` 은 요청마다 도는 사고를 응답과 어떤 순서로 돌릴지 정한다.

| 값 | 동작 | 언제 |
|---|---|---|
| `before` | 사고를 끝내고 응답. 해석이 이번 응답의 시스템 프롬프트에 섞인다 | 사고가 빠를 때 |
| `race` | `WAIT_SEC` 까지만 기다리고 늦으면 응답을 먼저 시작. 늦은 사고는 💭, open loop, 피드백 학습에만 쓰인다 | 사고와 메인이 다른 곳에서 돌 때(클라우드) |
| `after` | 응답이 끝난 뒤 사고 | 사고와 메인이 같은 GPU 를 나눠 쓸 때(로컬 Ollama) |

로컬 GPU 한 장에서 실측했을 때, `race` 는 두 모델이 GPU 를 나눠 써서 첫 글자가 21초 뒤에 나왔고 `after` 는 12.8초 뒤에 나왔다.

## 메모리와 세션

```bash
JARVIS_MEMORY__BACKEND=postgres            # in_memory | postgres
JARVIS_MEMORY__WINDOW_SIZE=50
JARVIS_MEMORY__COMPACTION_THRESHOLD=100000
JARVIS_MEMORY__CONSOLIDATE_ON_IDLE=true    # daemon_trigger 가 idle 또는 both 일 때 요약에서 사실 추출
JARVIS_MEMORY__EMBEDDING_PROVIDER=         # openai | ollama | vllm. 비우면 키워드 검색만
JARVIS_MEMORY__EMBEDDING_MODEL=nomic-embed-text
JARVIS_MEMORY__EMBEDDING_DIMENSIONS=768    # vllm 은 필수

JARVIS_SESSION__PERSISTENCE_BACKEND=jsonl  # jsonl | postgres
JARVIS_SESSION__SESSIONS_DIR=~/.jarvis/sessions
JARVIS_SESSION__POSTGRES_DSN=postgresql://user:pw@host:5432/jarvis

JARVIS_OPENLOOP__BACKEND=jsonl             # jsonl | in_memory | postgres
JARVIS_OPENLOOP__PATH=~/.jarvis/openloops.jsonl
JARVIS_OPENLOOP__EXPIRE_AFTER_SEC=21600    # 기한 뒤 이만큼 지나면 expired 로 닫음(6시간)
JARVIS_OPENLOOP__MAX_AGE_SEC=604800        # 기한 없는 약속의 수명(7일). 0 이면 닫지 않음
JARVIS_USER_MODEL__ENABLED=true
JARVIS_USER_MODEL__PATH=~/.jarvis/user_model.json
```

## 보안

```bash
JARVIS_SECURITY__API_KEYS='{"<long-random-key>": {"name": "jh", "roles": ["admin"]}}'
JARVIS_SECURITY__ALLOWED_ROLES=["user","admin"]
JARVIS_SECURITY__INPUT_MAX_LENGTH=10000
JARVIS_SECURITY__APPROVALS_PATH=~/.jarvis/approvals.yaml        # 공용 규칙(사람이 고친다)
JARVIS_SECURITY__AGENT_APPROVALS_DIR=~/.jarvis/approvals         # 에이전트별 규칙(<agent_id>.yaml, 항상 허용이 쌓인다)
```

`API_KEYS` 를 비우면 Web 인증이 꺼진다. 인증을 켜고 끄는 다른 스위치는 없다. TUI 는 설정과 상관없이 로컬 NoAuth 로 동작한다. 키가 곧 사용자 식별자이므로 길고 무작위인 값을 쓴다.

## MCP 서버

`mcp_servers` 는 목록 설정이다. 항목마다 `name`, `transport`(`stdio`, `http`), `command`, `url`, `env`, `headers`, `auth_token`, `timeout`(30)을 둔다. 항목 예시는 [확장하기](../concepts/extending.md) 에 있다.

## 절차 학습, 알림, 플러그인

```bash
JARVIS_PROCEDURES__ENABLED=true
JARVIS_PROCEDURES__DIR=~/.jarvis/procedures
JARVIS_PROCEDURES__MIN_TOOL_CALLS=3

JARVIS_NOTIFY__SLACK_WEBHOOK_URL=
JARVIS_NOTIFY__KINDS=["reminder","proactive"]

JARVIS_PLUGIN__TOOLS_DIR=~/.jarvis/tools
JARVIS_PLUGIN__SKILLS_DIR=./skills
JARVIS_PLUGIN__PLUGINS_DIR=~/.jarvis/plugins
JARVIS_PLUGIN__AGENTS_DIR=~/.jarvis/agents
```

`JARVIS_PLUGIN__WATCH_FILES` 는 설정에 있지만 현재 아무것도 감시하지 않는다. 파일을 더했으면 재시작한다.

## 음성

```bash
JARVIS_VOICE__STT_PROVIDER=browser      # browser | whisper
JARVIS_VOICE__TTS_PROVIDER=browser      # browser | supertonic
JARVIS_VOICE__TTS_LANG=ko
JARVIS_VOICE__TUI_ENABLED=false
JARVIS_VOICE__TUI_RECORD_SECONDS=5
```

whisper 모델 크기와 STT 언어 키는 설정 클래스에 있지만 현재 프로바이더가 읽지 않는다. whisper 는 한국어로 고정돼 있다.

## 화면과 브랜드

TUI 와 Web 은 환경변수가 아니라 `--web` 플래그로 고른다. 바인딩할 주소와 포트는 `--host`, `--port` 로 정한다.

```bash
TZ=Asia/Seoul                           # 스케줄과 /schedule 마감 시각의 기준 (compose 기본값)

JARVIS_BRAND__NAME=J.A.R.V.I.S.
JARVIS_BRAND__QUOTE=Proof the Heart
JARVIS_BRAND__PALETTE__PRIMARY=#5fc8e2
JARVIS_BRAND__PALETTE__ACCENT=#f0b35f
JARVIS_BRAND__PALETTE__BACKGROUND=#02060c
JARVIS_BRAND__PALETTE__NEBULA=["#3a5bff","#8a4dff","#ff6ad5"]
```

브랜드 값은 Web HUD 의 워드마크, 명언, 링과 구체 색에 들어간다. 에이전트마다 다르게 두면 어느 비서와 말하고 있는지 색으로 알 수 있다.

## 호스트 Ollama 팁

사고와 메인을 호스트의 Ollama 하나로 돌리면, 성찰이 도는 동안 사용자 요청이 줄을 선다. Ollama 를 brew 서비스로 띄웠다면 동시 처리 수를 늘린다.

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 2 && brew services restart ollama
```

:::warning

이 설정은 재부팅하면 사라진다. 재부팅한 뒤에는 위 명령을 다시 실행한다.

:::
