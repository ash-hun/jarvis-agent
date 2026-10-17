---
sidebar_position: 7
title: Extension
---

import FigureExtension from '@site/src/figures/extension.svg';

# Extension

<figure className="paper-fig">
  <FigureExtension />
  <figcaption><b>Figure 1.</b> (a) ~/.jarvis 아래에 놓는 파일과 설정. (b) 기동 때 읽혀 도구 레지스트리, 슬래시 커맨드, 서브 에이전트 도구가 되고, 플러그인은 에이전트 루프의 네 훅에 걸린다. 파일을 더했으면 재시작한다.</figcaption>
</figure>

`~/.jarvis/` 아래 폴더에 파일을 놓아 JARVIS 에 도구, 스킬, 플러그인, 에이전트를 더한다.

도구, 스킬, 플러그인, 에이전트 정의는 기동할 때 읽는다. 그래서 파일을 더했으면 재시작한다. 설정의 `WATCH_FILES` 는 아직 아무것도 감시하지 않는다.

## 도구

`~/.jarvis/tools/` 에 파이썬 파일 또는 YAML 선언을 둔다.

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

`~/.jarvis/skills/` 에 Markdown 파일을 둔다. frontmatter 의 `name` 이 `/name` 커맨드가 된다. 사용자가 커맨드 뒤에 쓴 글이 `{{args}}` 자리에 들어가고, 펼쳐진 본문이 LLM 프롬프트가 된다.

```markdown
---
name: summarize
description: 텍스트를 요약합니다
aliases: [sum, tldr]
---
다음 텍스트를 간결하게 요약해 주세요:

{{args}}
```

같은 이름의 `.py` 파일을 두면 `run(args, context)` 가 먼저 돌고, 그 반환 문자열이 프롬프트가 된다.

## 플러그인

플러그인은 에이전트 실행 흐름에 거는 훅이다. `~/.jarvis/plugins/` 에 클래스를 둔다.

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

실제로 불리는 훅은 `before_agent_start`, `before_tool_call`, `after_tool_call`, `on_message_end` 네 개다. `transform_context` 는 프로토콜에만 있고 호출되지 않는다. 플러그인 하나에서 난 오류는 격리된다.

:::note

정의하지 않은 훅이 있으면 그 훅을 부를 때마다 오류 로그가 남는다. 그래서 다섯 개를 모두 정의해 둔다.

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

## 메모리 미들웨어

`MemoryMiddleware` 프로토콜(`transform`, `store`, `retrieve`, `clear`)을 구현해 `MemoryMiddlewareChain` 에 끼운다. 체인은 턴마다 순서대로 돈다. 체인이 기억을 프롬프트에 넣는 흐름은 [Memory Management](./memory.md) 에 있다.

## 사고 프롬프트

요청 때 쓰는 사고 프롬프트는 `~/.jarvis/inner_thought.md` 에, 성찰 때 쓰는 프롬프트는 `~/.jarvis/inner_thought_reflection.md` 에 두어 바꾼다. 사고 프레임의 키 이름은 바꾸지 않는다.

:::note

템플릿에 `utterance` 키가 없으면 먼저 건네는 말이 꺼진 것과 같다.

:::

## 설계 노트

### 확장 지점은 같은 이름의 기반 클래스

확장 지점(프로바이더, 저장소, 훅, 사고 엔진 등)은 Protocol 이나 ABC 대신 같은 이름의 구체 기반 클래스로 만들었다. 기반 클래스에 기본 동작이 들어 있어서, 새 구현은 바꿀 메서드만 덮어쓰면 된다. 이 정리 때 Protocol 32개를 기반 클래스로 바꿨다.

### 사용자 확장은 재시작 없이 보이게

사용자 도구와 승인된 절차는 세션이 턴마다 도구 목록을 다시 읽어서, 등록하면 재시작 없이 다음 턴부터 보인다. 반면 승인 규칙 파일과 MCP 서버는 기동 때 한 번 읽으므로, 고친 뒤에는 서버를 다시 띄운다.
