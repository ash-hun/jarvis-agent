# Jarvis

A personal AI assistant agent built on a layered, extensible harness — inspired by the architecture of [Pi Agent Harness](https://github.com/anthropics/anthropic-quickstarts). Built with Python 3.11+, Textual TUI, and a forced 4-stage security pipeline.

<div align="center">
    <img src="./assets/screenshot.png" />
</div>


```
User Input → TUI → SecurityPipeline → AgentSession → AgentLoop → LLM (streaming)
                        ↓
              Validate → Authenticate → Policy → Sandbox
```

## Features

- **Multi-provider LLM** — Anthropic, OpenAI, Google, Ollama, vLLM (local), easily extensible
- **Pluggable memory middleware** — WindowMemory, SQLite persistence, LLM-based compaction, external DB adapters
- **File-based tools & skills** — Drop a `.py` or `.yaml` file, hot-reloads automatically
- **Forced security pipeline** — 4 ordered stages (input validation → auth → policy → sandbox), order cannot be bypassed
- **JSONL session persistence** — Append-only, git-friendly, with parent-id threading
- **Plugin hooks** — `before_tool_call`, `after_tool_call`, `transform_context`, etc.
- **Textual TUI** — Rich terminal UI with streaming output, `ctrl+k` to abort
- **Docker Compose** — Test and run without local setup

## Quick Start

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/your-username/jarvis.git
cd jarvis

uv sync
cp .env.example .env
# Edit .env — at minimum set JARVIS_LLM__API_KEY

jarvis
```

### With Docker

```bash
cp .env.example .env
# Edit .env

docker compose --profile app up jarvis
```

## Configuration

All settings are loaded from environment variables (prefix `JARVIS_`, nested delimiter `__`) or `.env`:

```bash
# LLM Provider
JARVIS_LLM__PROVIDER=anthropic        # anthropic | openai | google | ollama | vllm
JARVIS_LLM__MODEL=claude-sonnet-4-5
JARVIS_LLM__API_KEY=sk-...

# Local models (no API key needed)
JARVIS_LLM__PROVIDER=ollama
JARVIS_LLM__BASE_URL=http://localhost:11434
JARVIS_LLM__MODEL=llama3.2

# Memory backend
JARVIS_MEMORY__BACKEND=sqlite         # in_memory | sqlite | external

# Disable auth (personal / dev use)
JARVIS_SECURITY__REQUIRE_AUTH=false
```

See [`.env.example`](.env.example) for all available options.

## Architecture

```
config  ←  모든 레이어 (읽기 전용)
model_layer  ←  agent_layer  ←  core  ←  ui
```

| Layer | Path | Role |
|-------|------|------|
| `model_layer/` | `src/jarvis/model_layer/` | AsyncIterator-based multi-provider LLM abstraction |
| `agent_layer/` | `src/jarvis/agent_layer/` | State management, memory middleware chain, JSONL session |
| `core/` | `src/jarvis/core/` | Security pipeline, tool/skill/plugin registries, AgentSession |
| `ui/` | `src/jarvis/ui/` | Textual TUI (decoupled via `UIAdapter` Protocol) |

### Security Pipeline

The pipeline runs in a fixed order — stages cannot be skipped or reordered:

```
InputValidator → Authenticator → PolicyEngine → Sandbox
```

| Stage | Default impl | What it does |
|-------|--------------|--------------|
| `InputValidator` | `DefaultInputValidator` | Length check, XSS patterns, Unicode normalization |
| `Authenticator` | `NoAuthAuthenticator` | Always passes (for personal use); swap for `ApiKeyAuthenticator` or `JWTAuthenticator` |
| `PolicyEngine` | `AllowAllPolicy` | Role-based tool access control |
| `Sandbox` | `DefaultSandbox` | Blocks dangerous shell patterns, human-in-the-loop approval |

### Memory Middleware

Stages are applied sequentially via `MemoryMiddlewareChain`:

```
[WindowMemory] → [CompactionMiddleware] → [SqliteMemory] → ...
```

## Extending Jarvis

### Adding a Tool

**Option 1 — Python file** (`~/.jarvis/tools/my_tool.py`):

```python
TOOL_NAME = "my-tool"
TOOL_DESCRIPTION = "Does something useful"
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

async def execute(tool_call_id: str, params: dict, **kwargs) -> dict:
    return {"content": f"Result for: {params['query']}"}
```

**Option 2 — YAML + Python pair**:

```yaml
# my_tool.yaml
name: my-tool
description: "Does something useful"
execution_mode: parallel   # or sequential
parameters:
  type: object
  properties:
    query: {type: string}
  required: [query]
```

Drop either format into `JARVIS_PLUGIN__TOOLS_DIR` (default `~/.jarvis/tools/`). Changes are hot-reloaded.

### Adding a Skill (`/command`)

```markdown
---
name: summarize
description: Summarize the given text
aliases: [sum, tldr]
---
Please summarize the following text concisely:

{{args}}
```

Save as `~/.jarvis/skills/summarize.md`. Usage: `/summarize <text>` or `/sum <text>`.

### Adding a Plugin

```python
# ~/.jarvis/plugins/my_plugin.py
class MyPlugin:
    name = "my-plugin"
    version = "1.0.0"

    async def before_tool_call(self, tool_name: str, args: dict, auth) -> dict:
        print(f"About to call: {tool_name}")
        return args

    async def transform_context(self, messages: list) -> list:
        return messages
```

Plugin hooks: `before_agent_start`, `before_tool_call`, `after_tool_call`, `on_message_end`, `transform_context`.

### Adding a Memory Middleware

```python
from jarvis.agent_layer.memory.protocol import MemoryMiddleware

class MyMemory:
    async def transform(self, messages, context): return messages
    async def store(self, message, context): ...
    async def retrieve(self, query, context, limit): return []
    async def clear(self, context): ...
```

Register it in the `MemoryMiddlewareChain` during session setup.

## Built-in Skills

Skills live in the [`skills/`](skills/) directory and are loaded automatically when `JARVIS_PLUGIN__SKILLS_DIR=./skills`.

| Command | Aliases | Description |
|---------|---------|-------------|
| `/test` | `/t`, `/pytest`, `/ut` | Run the full unit test suite and report results |

**Usage examples:**

```
/test                          → runs all unit tests
/test -k "test_policy"         → runs only tests matching the keyword
/test tests/unit/test_config.py → runs a specific file
```

## Development

```bash
uv sync                          # install deps (includes dev extras)
uv run pytest                    # all tests (no real API calls)
uv run pytest -k "test_policy"   # specific test
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy src/                 # type check
```

### Running Tests with Docker

```bash
docker compose run --rm test
```

Tests use a `FauxProvider` (no API calls) with `JARVIS_SECURITY__REQUIRE_AUTH=false` and `JARVIS_MEMORY__BACKEND=in_memory`.

### Test Coverage

```
tests/unit/
├── test_config.py      — Pydantic Settings, env override, secrets
├── test_types.py       — Message/StreamEvent serialization
├── test_stream.py      — FauxProvider streaming, stream_to_message()
├── test_policy.py      — All 4 pipeline stages + SecurityPipeline end-to-end
├── test_memory.py      — MemoryMiddlewareChain, WindowMemory, compaction
├── test_tools.py       — ToolRegistry, BashTool, ReadFileTool
├── test_skills.py      — SkillRegistry, /command expansion, file loading
└── test_session.py     — AgentSession full flow (prompt, events, tools, abort)
```

## Project Structure

```
jarvis/
├── src/jarvis/
│   ├── config.py                      # Top-level Pydantic Settings
│   ├── model_layer/                   # LLM abstraction
│   │   ├── types.py                   # Message, StreamEvent, Tool
│   │   ├── stream.py                  # stream() / stream_to_message()
│   │   ├── registry.py                # ProviderRegistry
│   │   └── providers/                 # anthropic, openai, ollama, vllm
│   ├── agent_layer/                   # Stateful agent core
│   │   ├── loop.py                    # run_agent_loop()
│   │   ├── harness.py                 # AgentHarness
│   │   ├── memory/                    # Middleware chain + implementations
│   │   └── session/                   # JSONL session repo
│   ├── core/                          # Application core
│   │   ├── session.py                 # AgentSession (central hub)
│   │   ├── policy/                    # 4-stage security pipeline
│   │   ├── tools/                     # ToolRegistry + loader + builtins
│   │   ├── skills/                    # SkillRegistry + /command expansion
│   │   └── plugins/                   # PluginRunner + JarvisPlugin Protocol
│   └── ui/
│       ├── protocol.py                # UIAdapter Protocol
│       └── tui/                       # Textual TUI app
├── tests/
│   ├── conftest.py                    # Shared fixtures (FauxProvider, AgentSession)
│   ├── fixtures/faux_provider.py      # Test-only LLM provider
│   └── unit/                          # Unit tests (97 tests, 0 API calls)
├── Dockerfile                         # Multi-stage: base / test / runtime
├── docker-compose.yml
└── .env.example
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `bash` | Run shell commands (sequential execution, timeout support) |
| `read_file` | Read files with line numbers, offset/limit support |

## Roadmap

- [ ] Web UI (FastAPI + WebSocket, same `UIAdapter` Protocol)
- [ ] Google provider implementation
- [ ] Vector memory adapter (ChromaDB / pgvector)
- [ ] MCP (Model Context Protocol) tool bridge
- [ ] Session branching / tree navigation in TUI

## License

MIT
