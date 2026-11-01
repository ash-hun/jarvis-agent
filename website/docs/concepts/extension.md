---
sidebar_position: 7
title: Extension
---

import InfoExtension from '@site/src/figures/info-extension.svg';
import FigureExtension from '@site/src/figures/extension.svg';
import FigureExpExtension from '@site/src/figures/exp-extension.svg';

# Extension

Extension은 JARVIS 를 쓰는 사람이 코드를 고치지 않고 자기 도구, 명령, 훅, 에이전트를 더해 에이전트를 유기적으로 확장하는 방법이다. `~/.jarvis/` 아래 폴더에 파일을 놓으면 JARVIS 가 읽어 자기 기능으로 쓰고, 대화 중에 승인된 절차도 같은 길로 도구와 명령이 된다. 이 페이지는 확장 지점마다 무엇을 어디에 놓는지를 따라 하는 방법 위주로 정리한다.

<figure className="info-fig">
  <InfoExtension />
</figure>

## Extension이 주목한 점

사용자가 사내 API 를 부르는 도구나 자주 쓰는 요약 프롬프트를 에이전트에 붙이고 싶다고 하자. 많은 Agent Framework는 이때마다 저장소 코드를 고치고 서버를 다시 빌드하도록 요구하기 때문에, 작은 확장 하나에도 손이 많이 간다. 설정 파일로 일부를 열어 두는 프레임워크도 있지만, 고친 파일을 확인하려고 매번 서버를 다시 띄우면 진행 중이던 대화 흐름이 끊긴다. Jarvis-Agent는 정해진 폴더에 파일을 놓기만 하면 기능이 늘어나고, 고친 내용은 재시작 없이 다음 턴부터 반영되도록 설계했다.

### 어떤 기능을 가지고 있나요?

#### 확장 지점은 같은 이름의 기반 클래스

- 확장 지점(프로바이더, 저장소, 훅, 사고 엔진 등)은 같은 이름의 구체 기반 클래스로 만들었다. 다중 에이전트를 받도록 조립 층을 나눈 리팩터링(#84)에서 Protocol 32개와 ABC 를 기반 클래스로 바꿨다.
- 대안으로는 확장 지점을 Protocol 이나 ABC 로 정의하는 방식이 있었다.
- 기반 클래스에 기본 동작이 들어 있어서, 새 구현은 바꿀 메서드만 덮어쓰면 된다. [플러그인](#플러그인)에서 보듯 상속하지 않은 클래스는 훅을 모두 직접 정의해야 한다.

#### 승인된 절차는 재시작 없이 보이게

- 세션은 턴마다 도구 레지스트리를 다시 읽는다. 그래서 실행 중에 승인된 절차는 재시작 없이 다음 턴부터 도구로 보이고, 그 절차의 도구와 `/name` 스킬은 절차를 배운 에이전트에게만 보인다. `~/.jarvis/tools/`, `~/.jarvis/skills/`, `~/.jarvis/plugins/` 의 파일도 파일 감시가 다시 읽어 다음 턴부터 보인다.
- 대안으로는 기동 때 한 번 만든 도구 목록을 프로세스가 끝날 때까지 쓰는 방식이 있었다.
- 그렇게 하면 확장 하나를 고칠 때마다 서버를 다시 띄워야 하고 대화 흐름이 끊긴다. 다만 승인 규칙 파일과 MCP 서버는 지금도 기동 때 한 번 읽으므로, 고친 뒤에는 서버를 다시 띄운다.

## 세부 동작

### 한 눈에 보기

<figure className="paper-fig">
  <FigureExtension />
  <figcaption><b>Figure 1.</b> (a) ~/.jarvis 아래에 놓는 파일과 설정. (b) 기동 때 읽혀 도구 레지스트리, 슬래시 커맨드, 서브 에이전트 도구, 최상위 에이전트, 외부 이벤트 소스가 된다. 승인된 절차는 procedure_name 도구와 /name 스킬이 되고, 플러그인은 에이전트 루프의 네 훅에 걸린다. 기동 때 있던 tools, skills, plugins 디렉터리의 파일은 바꾸면 재시작 없이 다시 읽힌다. 새로 만든 디렉터리와 에이전트 정의는 재시작해야 반영된다.</figcaption>
</figure>

도구, 스킬, 플러그인, 에이전트 정의는 기동할 때 읽는다. `JARVIS_PLUGIN__WATCH_FILES`(기본 켜짐)가 켜져 있으면 기동 때 있던 도구, 스킬, 플러그인 디렉터리를 지켜보다(`app/extension_watcher.py`) 바뀐 디렉터리만 다시 읽는다. 같은 이름은 덮어써서 몇 번 다시 읽어도 하나다. 파일을 지운 확장, 기동 뒤에 만든 디렉터리, 에이전트 정의는 재시작해야 반영된다.

놓는 파일은 확장 지점마다 다르다. 도구는 파이썬 파일이나 YAML 선언, 외부 도구 서버는 MCP 서버 설정, 슬래시 명령은 Markdown 파일, 훅은 파이썬 플러그인, 서브 에이전트는 YAML 선언, 사고 방식은 사고 프롬프트 파일이다. 각각의 형식은 아래 절에 있다.

1. 기동할 때 `~/.jarvis/` 아래 파일을 읽어 도구 레지스트리, 슬래시 커맨드, 서브 에이전트 도구, 플러그인 훅을 채운다. MCP 서버 도구도 이때 등록한다.
2. 파일 감시가 켜져 있으면 기동 때 있던 도구, 스킬, 플러그인 디렉터리를 지켜본다.
3. 파일이 바뀌면 그 파일이 속한 디렉터리만 다시 읽는다. 한 디렉터리가 실패해도 다른 디렉터리는 읽는다.
4. 세션은 턴마다 도구 레지스트리를 다시 읽으므로, 바뀐 확장은 다음 턴부터 보인다.

### 도구

`~/.jarvis/tools/` 에 파이썬 파일 또는 YAML 선언을 둔다. 파이썬 파일은 `TOOL_NAME`(없으면 파일 이름의 `_` 를 `-` 로 바꾼 값), `TOOL_DESCRIPTION`, `TOOL_PARAMETERS` 와 `execute` 함수를 읽는다. `execute` 가 dict 를 돌려주면 `content` 키를, 아니면 값을 글자로 바꿔 결과로 쓴다. 예외는 `is_error` 결과가 된다.

```python
# ~/.jarvis/tools/my_tool.py
TOOL_NAME = "my-tool"
TOOL_DESCRIPTION = "유용한 작업 수행"
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

async def execute(tool_call_id: str, params: dict, **kwargs) -> dict:
    return {"content": f"결과: {params['query']}"}
```

YAML 선언은 메타데이터만 담고, 실행할 `execute` 는 같은 이름의 `.py` 파일에서 읽는다. `.py` 가 없으면 그 도구는 등록하지 않는다. YAML 이 있으면 같은 이름의 `.py` 를 따로 도구로 읽지 않는다.

```yaml
# ~/.jarvis/tools/my_tool.yaml
name: my-tool
description: "유용한 작업 수행"
execution_mode: parallel   # parallel | sequential
parameters:
  type: object
  properties:
    query: {type: string}
  required: [query]
```

### MCP 서버

[MCP](https://modelcontextprotocol.io) 서버를 설정하면 JARVIS 가 그 서버의 도구를 자동으로 발견해 등록한다. 전송 방식은 `stdio` 와 `http`(SSE) 를 지원한다. `uv sync --extra mcp` 로 설치해야 하고, 설치하지 않았으면 조용히 건너뛴다. 설정 키는 `mcp_servers` 목록이고, 환경변수로 줄 때는 `JARVIS_MCP_SERVERS` 에 JSON 배열로 넣는다.

```json
{"name": "filesystem", "transport": "stdio",
 "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"], "timeout": 30.0}

{"name": "remote-api", "transport": "http", "url": "https://mcp.example.com/sse",
 "auth_token": "sk-...", "headers": {"X-Org": "acme"}, "timeout": 30.0}
```

서버 하나가 실패하거나 타임아웃이 나도 다른 서버 로딩은 막히지 않는다. `timeout`(기본 30초) 안에 응답이 없으면 그 서버만 건너뛴다.

### 스킬(슬래시 커맨드)

`~/.jarvis/skills/` 에 Markdown 파일을 둔다. frontmatter 의 `name` 이 `/name` 커맨드가 된다. 사용자가 커맨드 뒤에 쓴 글이 `{{args}}`(또는 `{{input}}`) 자리에 들어가고, 펼쳐진 본문이 LLM 프롬프트가 된다.

```markdown
---
name: summarize
description: 텍스트를 요약합니다
aliases: [sum, tldr]
---
다음 텍스트를 간결하게 요약해 주세요:

{{args}}
```

스킬 파일은 `*.md` 와 `*.yaml` 만 읽는다. 스킬은 본문을 펼칠 뿐이고, 같은 이름의 `.py` 를 두어도 실행하지 않는다.

### 플러그인

플러그인은 에이전트 실행 흐름에 거는 훅이다. `~/.jarvis/plugins/` 의 `.py` 파일에 클래스를 둔다. 로더는 `name` 과 `version` 을 가진 첫 클래스를 인자 없이 만들어 등록한다.

```python
class MyPlugin:
    name = "my-plugin"
    version = "1.0.0"

    async def before_agent_start(self, prompt, context): ...
    async def before_tool_call(self, tool_name: str, args: dict, auth):
        return None                       # {"block": True, "reason": "..."} 을 돌려주면 호출이 막힌다
    async def after_tool_call(self, tool_name: str, args: dict, result: dict): ...
    async def on_message_end(self, message):
        return None                       # 메시지를 돌려주면 응답이 그것으로 바뀐다
    async def transform_context(self, messages: list):
        return messages
```

실제로 불리는 훅은 `before_agent_start`, `before_tool_call`, `after_tool_call`, `on_message_end` 네 개다. `after_tool_call` 의 `result` 에는 `is_error` 하나만 들어 있다. `transform_context` 는 기반 클래스에만 있고 호출되지 않는다. 플러그인 하나에서 난 오류는 격리된다.

:::note

상속하지 않은 클래스에 정의하지 않은 훅이 있으면 그 훅을 부를 때마다 오류 로그가 남는다. `jarvis.core.plugins.plugins_protocol.JarvisPlugin` 을 상속하면 덮어쓰지 않은 훅은 아무것도 하지 않는다. 상속하지 않으면 다섯 개를 모두 정의해 둔다.

:::

### 멀티 에이전트

`~/.jarvis/agents/` 에 YAML 로 에이전트를 선언한다. 하나씩 써도 되고 리스트로 여럿 써도 된다.

```yaml
- name: planner
  description: "작업을 단계로 나누는 기획자"
  capabilities: [계획]
  level: 0                 # hierarchical 에서 먼저 도는 레벨
  tools: [read_file]
  system_prompt: "당신은 기획자입니다."
  memory:
    stm: per_parent_session   # per_parent_session | per_task | per_agent
- name: writer
  description: "보고서 작성"
  capabilities: [작성, 보고서]
  level: 1
```

선언한 에이전트는 `/orchestrate <pattern> <task>` 로 부르거나, 메인 에이전트가 `orchestrate` 도구로 부른다. 패턴은 네 가지다.

- `supervisor`: 감독자 LLM 이 위임을 결정한다
- `hierarchical`: 레벨 순으로 돌고, 앞 결과가 뒤로 넘어간다
- `market`: capabilities 가 맞는 에이전트 하나가 맡는다
- `blackboard`: 전원이 병렬로 돌고 결과를 취합한다

패턴을 쉼표로 이으면 파이프라인이 된다. 서브 에이전트는 부모의 사용자 범위를 상속하고, 부모는 위임한 일을 일화로 기억한다. 패턴별 흐름은 [Orchestration Pattern](./multi-agent-orchestration/orchestration-pattern.md) 에 있다.

### LLM 프로바이더

LLM 프로바이더를 더하려면 `src/jarvis/model_layer/providers/` 에 `stream()` 하나를 구현하고 레지스트리에 등록한다.

```python
async def stream(model: ModelConfig, ctx: LLMContext, options) -> AsyncIterator[StreamEvent]:
    yield TextDeltaEvent(delta="Hello")
    yield StopEvent(reason="stop", usage=Usage())
```

### 메모리 저장소

메모리 미들웨어 체인은 없어졌다. 기억은 `MemoryService` 하나가 맡고, 바꿀 수 있는 곳은 저장소다. 장기 기억 저장소는 `memory/stores/store_protocol.py` 의 `ItemStore`, 작업 기억 저장소는 `memory/working/state.py` 의 `WorkingStore`, 임베딩은 `model_layer/embeddings.py` 의 `Embedder` 를 상속해 만들고 `MemoryService` 에 넘긴다. 기본 구현은 메모리와 Postgres 다. 기억을 프롬프트에 넣는 흐름은 [Memory Management](./memory.md) 에 있다.

### 사고 프롬프트

요청 때 쓰는 사고 프롬프트는 `~/.jarvis/inner_thought.md` 에, 성찰 때 쓰는 프롬프트는 `~/.jarvis/inner_thought_reflection.md` 에 두어 바꾼다. 사고 프레임의 키 이름은 바꾸지 않는다.

:::note

템플릿에 `utterance` 키가 없으면 Proactive Dialogue 가 꺼진 것과 같다.

:::

### 한계

- 파일을 지운 확장은 재시작 전까지 남는다. 다시 읽기는 같은 이름을 덮어쓸 뿐 빠진 이름을 지우지 않는다
- 기동 뒤에 만든 디렉터리는 지켜보지 않는다. 디렉터리를 새로 만들었으면 재시작한다
- 에이전트 정의, 승인 규칙 파일, MCP 서버 설정은 기동 때 한 번 읽으므로 고친 뒤에는 서버를 다시 띄운다
- 플러그인의 `transform_context` 훅은 호출되지 않는다

### 구현 위치

- 파일 감시: `app/extension_watcher.py`(`ExtensionWatcher`), 기동 때 조립은 `app/infra_builder.py`
- 플러그인 기반 클래스: `core/plugins/plugins_protocol.py` 의 `JarvisPlugin`
- 서브 에이전트 정의 로더: `core/multi_agent/multi_agent_loader.py`
- LLM 프로바이더: `model_layer/providers/`
- 메모리 저장소: `memory/stores/store_protocol.py`, `memory/working/state.py`, `model_layer/embeddings.py`

## Performance Experiments

도구 파일을 고친 뒤 재시작 없이 얼마나 빨리 쓸 수 있는지를 실험으로 확인했다.

### 도구 파일을 고친 뒤 쓸 수 있을 때까지 걸린 시간

- **질문**: 도구 파일을 넣거나 고친 뒤, 재시작 없이 그 도구를 부를 수 있을 때까지 얼마나 걸리나. 파일 감시가 없던 때와 비교하면 어떤가
- **설정**: 실제 `ExtensionWatcher`, watchfiles 1.3.0, `ToolLoader`, `ToolRegistry` 를 macOS 임시 디렉터리에 띄우고 레지스트리를 2ms 마다 확인했다. 새 파일과, 크기가 바뀌는 수정(편집기 저장처럼 원자적 교체)을 각각 30회 쟀다. 비교 대상은 감시가 없던 #195 전 코드(eb41779)와, 새 프로세스에서 앱을 조립하는 재시작 비용(10회)이다
- **결과**:

<figure className="paper-fig">
  <FigureExpExtension />
  <figcaption><b>Figure 2.</b> 감시가 켜져 있으면 새 파일과 고친 파일 모두 0.1초 안팎에 반영된다. 재시작 막대는 프로세스 시작과 앱 조립만 잰 값이라 실제 재시작보다 짧다.</figcaption>
</figure>

| 측정 | p50 | p95 | 최대 | 횟수 |
|---|---|---|---|---|
| 새 파일, 감시 켬 | 77.1ms | 122.6ms | 123.8ms | 30회, 시간 초과 0 |
| 고친 파일, 감시 켬 | 78.0ms | 94.7ms | 123.3ms | 30회, 시간 초과 0, 바뀐 뒤 호출 30/30 |
| 같은 크기로 1초 안에 다시 저장 | 3초 안에 30/30 반영 | | | 30회(캐시 수정 전 9/30) |
| 새 파일, #195 전 | 5초 뒤에도 보이지 않음 | | | 1회 |
| 재시작(프로세스와 앱 조립), 지금 코드 | 289.6ms | 394.9ms | 394.9ms | 10회 |
| 재시작(프로세스와 앱 조립), #195 전 | 292.7ms | 395.6ms | 395.6ms | 10회 |

- **해석**: 도구를 고치는 개발 루프에서 서버를 다시 띄울 필요가 없어졌다. 재시작은 이 측정에 넣지 않은 비용(컨테이너 재시작, uvicorn 기동, WebSocket 재연결, 메모리에 있던 세션)이 더 붙으므로, 실제 차이는 표보다 크다
- **실험에서 찾아 고친 것**: 처음 쟀을 때는 크기가 같은 수정을 1초 안에 다시 저장하면 30번 중 9번만 반영됐다. Python 바이트코드 캐시가 소스 크기와 초 단위 수정 시각으로만 낡았는지 판단해 예전 캐시를 썼다. 도구 로더가 캐시를 읽지 않고 매번 소스를 컴파일하게 바꾼 뒤 30/30 이 됐다
- **한계**: macOS FSEvents 에서만 쟀고, skills 와 plugins 디렉터리는 재지 않았다
- **재현**: `uv run python scripts/experiments/tool_reload.py --label <코드 이름> --mode watch` (`--mode static`, `--mode restart` 로 비교 대상)
