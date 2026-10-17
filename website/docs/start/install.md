---
sidebar_position: 2
title: Quick Start
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Quick Start

jarvis-agent 를 내려받아 TUI 나 Web HUD 로 띄운다. 로컬에서 uv 로 띄우는 방법과 Docker 로 전체 스택을 띄우는 방법이 있고, 둘 중 하나만 고르면 된다.

## 실행환경

- Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)
- LLM 하나. 클라우드 API 키가 있거나 로컬에 Ollama, vLLM 이 떠 있어야 한다
- Docker(선택). Web HUD 전체 스택(nginx, 백엔드, Postgres)을 한 번에 띄울 때만 쓴다

## 서비스 구동방법

<Tabs groupId="runtime">
<TabItem value="uv" label="로컬 (uv)" default>

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

`.env.example` 은 세션과 메모리 백엔드를 `postgres` 로 둔다. Docker 없이 띄우려면 두 줄을 `jsonl` 과 `in_memory` 로 바꾼다. 그러면 세션이 `~/.jarvis/sessions/` 에 JSONL 로 쌓인다.

기존 세션을 이어 가려면 `jarvis -s <session_id>` 를 쓰고, 세션 목록은 `jarvis --list-sessions` 로 본다.

</TabItem>
<TabItem value="docker" label="Docker">

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

컨테이너는 `./src` 를 그대로 마운트한다. 파이썬을 고친 뒤에는 이미지를 다시 만들지 않고 `docker compose restart jarvis-backend` 로 반영한다. 정적 파일은 nginx 가 바로 서빙하므로 새로고침만 하면 된다.

컨테이너 안에서 호스트의 Ollama 를 쓰려면 `JARVIS_LLM__BASE_URL=http://host.docker.internal:11434` 로 둔다.

:::warning[WARNING]
새 의존성이 들어간 버전으로 올렸다면 `./src` 마운트만으로는 반영되지 않는다. `docker compose build` 로 이미지를 다시 만든다.
:::

</TabItem>
</Tabs>

## LLM Provider 선택

로컬 LLM(Ollama, vLLM)과 클라우드 LLM API(Anthropic, OpenAI, Google)를 연동할 수 있다. 프로바이더는 환경변수 `JARVIS_LLM__PROVIDER` 로 고른다.

| 프로바이더 | `JARVIS_LLM__PROVIDER` | API 키 |
|---|---|---|
| Anthropic (Claude) | `anthropic` | 필요 |
| OpenAI (GPT) | `openai` | 필요 |
| Google (Gemini) | `google` | 필요, `uv sync --extra gemini` |
| Ollama (로컬) | `ollama` | 불필요 |
| vLLM (로컬) | `vllm` | 불필요 |

<Tabs groupId="model-host">
<TabItem value="cloud" label="클라우드" default>

```bash
JARVIS_LLM__PROVIDER=anthropic
JARVIS_LLM__MODEL=claude-sonnet-4-5
JARVIS_LLM__API_KEY=sk-ant-...
```

</TabItem>
<TabItem value="local" label="로컬">

```bash
JARVIS_LLM__PROVIDER=ollama
JARVIS_LLM__BASE_URL=http://localhost:11434
JARVIS_LLM__MODEL=gemma4:e4b
```

</TabItem>
</Tabs>

메인 모델은 도구 호출과 JSON 출력을 지원해야 한다. 로컬에서 검증한 조합은 메인 `gemma4:e4b`, 사고 전용 `gemma4:e2b-it-qat` 이다. 사고 모델을 따로 두는 방법은 [서비스 설정 값](../reference/configuration.md)에 있다.

:::warning[WARNING]
클라우드 프로바이더는 요청마다 비용이 든다. JARVIS 는 응답 한 번에 메인 호출 외에 사고 호출을 한 번 더 하고, 요청이 없을 때도 주기적으로 성찰 호출을 한다. 비용이 걱정되면 사고 모델을 작은 모델이나 로컬 모델로 따로 둔다.
:::
