---
sidebar_position: 7
title: Extension
---

import FigureExtension from '@site/src/figures/extension.svg';

# Extension

<figure className="paper-fig">
  <FigureExtension />
  <figcaption><b>Figure 1.</b> (a) ~/.jarvis 아래에 놓는 파일과 설정. (b) 기동 때 읽혀 도구 레지스트리, 슬래시 커맨드, 서브 에이전트 도구, 최상위 에이전트, 외부 이벤트 소스가 된다. 승인된 절차는 procedure_name 도구와 /name 스킬이 되고, 플러그인은 에이전트 루프의 네 훅에 걸린다. 파일을 더했으면 재시작한다.</figcaption>
</figure>

`~/.jarvis/` 아래 폴더에 파일을 놓아 JARVIS 에 도구, 스킬, 플러그인, 에이전트를 더한다.

도구, 스킬, 플러그인, 에이전트 정의는 기동할 때 읽는다. 그래서 파일을 더했으면 재시작한다. 설정의 `WATCH_FILES` 는 아직 아무것도 감시하지 않는다(`ToolLoader.watch` 가 있지만 부르는 곳이 없다).

## 도구

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

## MCP 서버

[MCP](https://modelcontextprotocol.io) 서버를 설정하면 JARVIS 가 그 서버의 도구를 자동으로 발견해 등록한다. 전송 방식은 `stdio` 와 `http`(SSE) 를 지원한다. `uv sync --extra mcp` 로 설치해야 하고, 설치하지 않았으면 조용히 건너뛴다. 설정 키는 `mcp_servers` 목록이고, 환경변수로 줄 때는 `JARVIS_MCP_SERVERS` 에 JSON 배열로 넣는다.

```json
{"name": "filesystem", "transport": "stdio",
 "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"], "timeout": 30.0}

{"name": "remote-api", "transport": "http", "url": "https://mcp.example.com/sse",
 "auth_token": "sk-...", "headers": {"X-Org": "acme"}, "timeout": 30.0}
```

서버 하나가 실패하거나 타임아웃이 나도 다른 서버 로딩은 막히지 않는다. `timeout`(기본 30초) 안에 응답이 없으면 그 서버만 건너뛴다.

## 스킬(슬래시 커맨드)

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

## 플러그인

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

## 멀티 에이전트

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

## LLM 프로바이더

LLM 프로바이더를 더하려면 `src/jarvis/model_layer/providers/` 에 `stream()` 하나를 구현하고 레지스트리에 등록한다.

```python
async def stream(model: ModelConfig, ctx: LLMContext, options) -> AsyncIterator[StreamEvent]:
    yield TextDeltaEvent(delta="Hello")
    yield StopEvent(reason="stop", usage=Usage())
```

## 메모리 저장소

메모리 미들웨어 체인은 없어졌다. 기억은 `MemoryService` 하나가 맡고, 바꿀 수 있는 곳은 저장소다. 장기 기억 저장소는 `memory/stores/store_protocol.py` 의 `ItemStore`, 작업 기억 저장소는 `memory/working/state.py` 의 `WorkingStore`, 임베딩은 `model_layer/embeddings.py` 의 `Embedder` 를 상속해 만들고 `MemoryService` 에 넘긴다. 기본 구현은 메모리와 Postgres 다. 기억을 프롬프트에 넣는 흐름은 [Memory Management](./memory.md) 에 있다.

## 사고 프롬프트

요청 때 쓰는 사고 프롬프트는 `~/.jarvis/inner_thought.md` 에, 성찰 때 쓰는 프롬프트는 `~/.jarvis/inner_thought_reflection.md` 에 두어 바꾼다. 사고 프레임의 키 이름은 바꾸지 않는다.

:::note

템플릿에 `utterance` 키가 없으면 Proactive Dialogue 가 꺼진 것과 같다.

:::

## 설계 노트

### 확장 지점은 같은 이름의 기반 클래스

확장 지점(프로바이더, 저장소, 훅, 사고 엔진 등)은 Protocol 이나 ABC 대신 같은 이름의 구체 기반 클래스로 만들었다. 기반 클래스에 기본 동작이 들어 있어서, 새 구현은 바꿀 메서드만 덮어쓰면 된다. 다중 에이전트를 받도록 조립 층을 나눈 리팩터링(#84)에서 Protocol 32개와 ABC 를 기반 클래스로 바꿨다.

### 승인된 절차는 재시작 없이 보이게

세션은 턴마다 도구 레지스트리를 다시 읽는다. 그래서 실행 중에 승인된 절차는 재시작 없이 다음 턴부터 도구로 보인다. 반면 `~/.jarvis/tools/` 의 사용자 도구 파일, 승인 규칙 파일, MCP 서버는 기동 때 한 번 읽으므로, 고친 뒤에는 서버를 다시 띄운다.
