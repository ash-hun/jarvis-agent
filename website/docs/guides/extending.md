---
sidebar_position: 5
title: 확장하기
---

# 확장하기

`~/.jarvis/` 아래 폴더에 파일을 놓는 것이 확장의 기본 방식이다. 도구, 스킬, 플러그인, 에이전트 정의는 기동 때 읽는다. 더했으면 재시작한다(설정의 `WATCH_FILES` 는 아직 아무것도 감시하지 않는다).

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

[MCP](https://modelcontextprotocol.io) 서버의 도구를 자동으로 발견해 등록한다. `stdio` 와 `http`(SSE) 를 지원한다. `uv sync --extra mcp` 가 필요하고, 없으면 조용히 건너뛴다. 설정은 `mcp_servers` 목록이고 환경변수로는 `JARVIS_MCP_SERVERS` 에 JSON 배열로 준다.

```json
{"name": "filesystem", "transport": "stdio",
 "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"], "timeout": 30.0}

{"name": "remote-api", "transport": "http", "url": "https://mcp.example.com/sse",
 "auth_token": "sk-...", "headers": {"X-Org": "acme"}, "timeout": 30.0}
```

서버 하나의 실패나 타임아웃이 다른 서버 로딩을 막지 않는다. `timeout`(기본 30초) 안에 응답이 없으면 그 서버만 건너뛴다.

## 스킬(슬래시 커맨드)

`~/.jarvis/skills/` 에 Markdown 을 둔다. frontmatter 의 `name` 이 `/name` 이 된다. `{{args}}` 자리에 사용자가 뒤에 쓴 글이 들어가고, 펼쳐진 본문이 LLM 프롬프트가 된다.

```markdown
---
name: summarize
description: 텍스트를 요약합니다
aliases: [sum, tldr]
---
다음 텍스트를 간결하게 요약해 주세요:

{{args}}
```

같은 이름의 `.py` 를 두면 `run(args, context)` 가 먼저 돌고 반환 문자열이 프롬프트가 된다.

## 플러그인

에이전트 실행 흐름의 훅. `~/.jarvis/plugins/` 에 클래스를 둔다.

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

실제로 불리는 훅은 `before_agent_start`, `before_tool_call`, `after_tool_call`, `on_message_end` 다. `transform_context` 는 프로토콜에만 있고 호출되지 않는다. 훅을 정의하지 않으면 그 훅에서 오류 로그가 남으므로 다섯 개를 다 둔다. 플러그인 하나의 오류는 격리된다.

## 멀티 에이전트

`~/.jarvis/agents/` 에 YAML 로 에이전트를 선언한다. 하나씩 또는 리스트로.

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

호출은 `/orchestrate <pattern> <task>` 또는 메인 에이전트의 `orchestrate` 도구. 패턴은 `supervisor`(감독자 LLM 이 위임 결정), `hierarchical`(레벨 순, 앞 결과가 뒤로), `market`(capabilities 가 맞는 하나), `blackboard`(전원 병렬, 결과 취합). 쉼표로 이으면 파이프라인. 서브 에이전트는 부모의 사용자 범위를 상속하고, 부모는 위임을 일화로 기억한다. 자세한 흐름은 [멀티 에이전트](../concepts/multi-agent.md).

## LLM 프로바이더

`src/jarvis/model_layer/providers/` 에 `stream()` 하나를 구현하고 레지스트리에 등록한다.

```python
async def stream(model: ModelConfig, ctx: LLMContext, options) -> AsyncIterator[StreamEvent]:
    yield TextDeltaEvent(delta="Hello")
    yield StopEvent(reason="stop", usage=Usage())
```

## 메모리 미들웨어

`MemoryMiddleware` 프로토콜(`transform`, `store`, `retrieve`, `clear`)을 구현해 `MemoryMiddlewareChain` 에 끼운다. 턴마다 체인이 순서대로 돈다. [메모리](../concepts/memory.md) 를 보라.

## 사고 프롬프트

`~/.jarvis/inner_thought.md`(요청), `~/.jarvis/inner_thought_reflection.md`(성찰). 프레임의 키 이름은 바꾸지 않는다. `utterance` 가 없으면 먼저 말하는 기능이 꺼진 것과 같다.
