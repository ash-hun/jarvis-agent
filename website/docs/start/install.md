---
sidebar_position: 2
title: Quick Start
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

# Quick Start

처음 Jarvis-Agent 를 접하는 사용자가 가장 빠르게 에이전트와 대화를 시작할 수 있도록 설치와 실행 방법을 정리한다. 저장소를 내려받고, LLM 을 하나 고르고, Web HUD 를 띄우면 된다. 실행 방법은 로컬에서 uv 로 띄우는 방법과 Docker 로 전체 스택을 띄우는 방법 중 하나만 고른다.

## 준비물

- Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)
- LLM 하나. 클라우드 API 키가 있거나 로컬에 Ollama, vLLM 이 떠 있어야 한다
- Docker(선택). Web HUD 전체 스택(nginx, 백엔드, Postgres)을 한 번에 띄울 때만 쓴다
- Node.js(선택). 데스크톱 앱을 쓸 때만 필요하다

## LLM Provider 고르기

로컬 LLM(Ollama, vLLM)과 클라우드 LLM API(Anthropic, OpenAI, Google Gemini)를 연동할 수 있다. 프로바이더는 `.env` 의 `JARVIS_LLM__PROVIDER` 로 고르고, 실행하기 전에 정해 둔다.

| 프로바이더 | `JARVIS_LLM__PROVIDER` | API 키 |
|---|---|---|
| Anthropic (Claude) | `anthropic` | 필요 |
| OpenAI (GPT) | `openai` | 필요 |
| Google (Gemini) | `gemini` | 필요, `uv sync --extra gemini` |
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

## 실행하기

<Tabs groupId="runtime">
<TabItem value="uv" label="로컬 (uv)" default>

1. 저장소를 내려받고 의존성을 설치한다.

   ```bash
   git clone https://github.com/ash-hun/jarvis-agent.git
   cd jarvis-agent
   uv sync --extra web --extra scheduler
   ```

2. 설정 파일을 만든다. `.env` 에서 최소 `JARVIS_LLM__API_KEY` 를 채운다(Ollama 면 비워도 된다).

   ```bash
   cp .env.example .env
   ```

   `.env.example` 은 세션과 메모리 백엔드를 `postgres` 로 둔다. Docker 없이 띄우려면 두 줄을 `jsonl` 과 `in_memory` 로 바꾼다. 그러면 세션이 `~/.jarvis/sessions/` 에 JSONL 로 쌓인다.

3. 백엔드를 띄운다. 예전처럼 `--web` 을 붙여도 같다.

   ```bash
   jarvis                            # Web HUD, http://localhost:7777
   jarvis --host 0.0.0.0 --port 8080 # 바인딩 바꾸기
   ```

기존 세션을 이어 가려면 `jarvis -s <session_id>` 를 쓰고, 세션 목록은 `jarvis --list-sessions` 로 본다. `jarvis -a karen` 처럼 `-a` 로 에이전트를 고르면 그 에이전트의 기본 세션(`default-karen`)을 연다. 모든 옵션은 `jarvis -h` 로 본다.

</TabItem>
<TabItem value="docker" label="Docker">

1. 설정 파일을 만들고 LLM 값을 채운다.

   ```bash
   cp .env.example .env
   ```

2. `web` 프로파일로 띄운다. 끌 때는 `down` 을 쓴다.

   ```bash
   docker compose --profile web up -d  # nginx + 백엔드 + Postgres, http://localhost:7777
   docker compose --profile web down
   ```

| 프로파일 | 서비스 | 접속 |
|---|---|---|
| `web` | nginx, jarvis-backend, postgres | http://localhost:7777 |

`web` 백엔드 이미지는 `web`, `scheduler`, `voice`, `piper`, `wake`, `discord` extra 와 ffmpeg 를 넣어 빌드하므로 따로 설치할 것이 없다. 저장소의 `team/`(최상위 에이전트 정의)과 `models/`(음성 모델)는 읽기 전용으로 마운트한다.

백엔드 컨테이너는 `./src` 를 그대로 마운트한다. 파이썬을 고친 뒤에는 이미지를 다시 만들지 않고 `docker compose restart jarvis-backend` 로 반영한다. 정적 파일은 nginx 가 바로 서빙하므로 새로고침만 하면 된다.

컨테이너 안에서 호스트의 Ollama 를 쓰려면 `JARVIS_LLM__BASE_URL=http://host.docker.internal:11434` 로 둔다.

:::warning[WARNING]
새 의존성이 들어간 버전으로 올렸다면 `./src` 마운트만으로는 반영되지 않는다. `docker compose build` 로 이미지를 다시 만든다.
:::

</TabItem>
</Tabs>

## 데스크톱 앱으로 쓰기

`desktop/` 의 Electron 앱은 HUD 를 창 하나로 연다. 백엔드가 떠 있지 않으면 `docker compose --profile web up -d` 를 대신 실행하고, 창을 닫아도 트레이에 남아 먼저 건네는 말과 알림을 OS 알림으로 띄운다. 단축키 `CommandOrControl+Shift+J` 를 누르면 창이 앞으로 오고 바로 듣기 시작한다.

```bash
cd desktop && npm install && npm start
```

## 확인하기

Web HUD 로 띄웠다면 브라우저에서 http://localhost:7777 을 연다. 헤더 이름 옆 점이 깜빡이면 연결된 것이고, 메시지를 보내면 `THINKING` 자리표시 뒤에 응답이 스트리밍으로 나온다. 데스크톱 앱이라면 창이 같은 화면을 연다. 응답이 오지 않거나 설정이 반영되지 않는 것 같으면 [FAQ](../troubleshooting/index.md)에서 증상에 맞는 페이지를 찾는다.

## 다음 할 일

- 화면 영역과 조작은 [Web HUD 사용가이드](./web-hud.md)에 있다
- 대화가 어떻게 흘러가는지는 [Conversation](../concepts/conversation/index.md)에서 본다
- 모델, 저장소, 음성 설정은 [서비스 설정 값](../reference/configuration.md)에서 바꾼다
