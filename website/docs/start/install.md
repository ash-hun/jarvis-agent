---
sidebar_position: 2
title: 설치와 실행
---

# 설치와 실행

## 요구사항

- Python 3.11 이상, [uv](https://docs.astral.sh/uv/)
- LLM 하나. 클라우드 API 키 또는 로컬 Ollama, vLLM
- Docker 는 선택. Web HUD 전체 스택(nginx, 백엔드, Postgres)을 한 번에 띄울 때 쓴다

## 로컬 실행

```bash
git clone https://github.com/ash-hun/jarvis-agent.git
cd jarvis-agent

uv sync --extra web --extra scheduler
cp .env.example .env
# .env 에서 최소 JARVIS_LLM__API_KEY 를 채운다 (Ollama 면 비워도 된다)

jarvis                                  # TUI
jarvis --web                            # Web HUD, http://localhost:7777
jarvis --web --host 0.0.0.0 --port 8080 # 바인딩 바꾸기
```

`.env.example` 은 세션과 메모리 백엔드가 `postgres` 로 되어 있다. Docker 없이 바로 띄우려면 두 줄을 `jsonl` 과 `in_memory` 로 바꾼다. 세션은 그러면 `~/.jarvis/sessions/` 에 JSONL 로 쌓인다. 기존 세션을 이어가려면 `jarvis -s <session_id>`, 목록은 `jarvis --list-sessions`.

## Docker 실행

```bash
cp .env.example .env

docker compose --profile app up jarvis        # TUI + Postgres
docker compose --profile web up -d            # nginx + 백엔드 + Postgres, http://localhost:7777
docker compose --profile web down
```

| 프로파일 | 서비스 | 접속 |
|---|---|---|
| `app` | jarvis TUI, postgres | 터미널 |
| `web` | nginx, jarvis-backend, postgres | http://localhost:7777 |

컨테이너는 `./src` 를 그대로 마운트한다. 파이썬을 고치면 이미지를 다시 만들지 않고 `docker compose restart jarvis-backend` 로 반영된다. 정적 파일은 nginx 가 바로 서빙하므로 새로고침이면 된다.

컨테이너 안에서 호스트의 Ollama 를 쓰려면 `JARVIS_LLM__BASE_URL=http://host.docker.internal:11434`.

## LLM 프로바이더 고르기

| 프로바이더 | `JARVIS_LLM__PROVIDER` | API 키 |
|---|---|---|
| Anthropic (Claude) | `anthropic` | 필요 |
| OpenAI (GPT) | `openai` | 필요 |
| Google (Gemini) | `google` | 필요, `uv sync --extra gemini` |
| Ollama (로컬) | `ollama` | 불필요 |
| vLLM (로컬) | `vllm` | 불필요 |

```bash
# 클라우드
JARVIS_LLM__PROVIDER=anthropic
JARVIS_LLM__MODEL=claude-sonnet-4-5
JARVIS_LLM__API_KEY=sk-ant-...

# 로컬
JARVIS_LLM__PROVIDER=ollama
JARVIS_LLM__BASE_URL=http://localhost:11434
JARVIS_LLM__MODEL=gemma4:e4b
```

메인 모델은 도구 호출과 JSON 출력이 되어야 한다. 로컬에서 검증된 조합은 메인 `gemma4:e4b`, 사고 전용 `gemma4:e2b-it-qat` 이다. [설정](../reference/configuration.md) 의 사고 모델 항목을 보라.

## 처음 켜면

1. `.env` 를 채운다. 프로바이더, 모델, 키
2. TUI 또는 Web HUD 를 띄운다
3. "안녕" 한 마디를 보낸다. 💭 한 줄이 뜨면 내적 사고가 켜진 것이다
4. `bash` 를 쓰는 요청을 해 본다. 승인 모달이 뜨면 `ALLOW`. `ALWAYS` 를 누르면 그 패턴은 다시 묻지 않는다
5. 2분 뒤 🔔 가 뜨는지 본다. 안 뜨면 백엔드 로그의 `[Thought] proactive silent: <이유>` 가 답이다

## 선택 의존성

```bash
uv sync --extra web          # Web HUD (FastAPI, uvicorn). 없으면 --web 이 안 뜬다
uv sync --extra scheduler    # /schedule 의 cron 과 AGENDA 의 다음 실행 시각
uv sync --extra mcp          # MCP 서버 연결
uv sync --extra gemini       # Google Gemini
uv sync --extra voice        # 서버 STT(faster-whisper), TTS(supertonic)
```
