# Jarvis Architecture Design

> **Status:** Draft — 설계 확정 전
> **Date:** 2026-05-17
> **Baseline:** [pi-reference.md](./pi-reference.md) (Pi Agent Harness TypeScript → Python 변환)

---

## 개요

Pi의 5개 패키지 계층을 Python 단일 패키지 + 레이어드 서브모듈로 변환.  
Pi의 핵심 설계 철학(streaming as AsyncIterator, middleware chain, Protocol-based registry, forced security pipeline)을 Python asyncio/Pydantic v2로 충실히 재현.

**Tech Stack**
| 항목 | 선택 |
|------|------|
| 언어 | Python 3.11+ |
| 패키지 관리 | uv |
| TUI | Textual |
| 스키마/설정 | Pydantic v2 + pydantic-settings |
| 비동기 | asyncio + anyio |
| LLM 추상화 | litellm (내부 레이어에서만) + 자체 ai/ 레이어 |
| 보안 | python-jose (JWT), pycryptodome |
| 스토리지 | aiosqlite, aiofiles (JSONL) |
| 플러그인 | watchfiles (핫리로드) |
| 테스트 | pytest-asyncio, faux provider |
| 린팅 | ruff (line-length 120) |

---

## 디렉토리 구조

```
jarvis/
├── pyproject.toml
├── .env.example
├── CLAUDE.md
│
├── src/
│   └── jarvis/
│       ├── config.py                  # Pydantic Settings 최상위 진입점
│       │
│       ├── model_layer/               # Layer 1: LLM 추상화 (Pi: pi-ai)
│       │   ├── types.py                 # Message, StreamEvent, Tool 타입
│       │   ├── stream.py                # AsyncIterator 스트리밍 진입점
│       │   ├── registry.py              # Provider 등록/조회
│       │   └── providers/
│       │       ├── base.py              # ProviderStreamFn Protocol
│       │       ├── anthropic.py
│       │       ├── openai.py
│       │       ├── google.py
│       │       ├── ollama.py            # 로컬 Ollama
│       │       └── vllm.py              # 로컬 vLLM
│       │
│       ├── agent_layer/               # Layer 2: Stateful Agent Core (Pi: pi-agent-core)
│       │   ├── types.py                 # AgentContext, AgentEvent, AgentState
│       │   ├── loop.py                  # run_agent_loop()
│       │   ├── harness.py               # AgentHarness
│       │   ├── memory/
│       │   │   ├── protocol.py          # MemoryMiddleware Protocol
│       │   │   ├── chain.py             # MemoryMiddlewareChain
│       │   │   ├── in_memory.py         # WindowMemory
│       │   │   ├── sqlite.py            # SqliteMemory
│       │   │   ├── compaction.py        # Pi: compact() 패턴
│       │   │   └── adapters/
│       │   │       ├── vector.py        # 벡터 DB 어댑터
│       │   │       └── external.py      # 외부 DB 연동
│       │   └── session/
│       │       ├── protocol.py          # SessionRepo Protocol
│       │       └── jsonl.py             # JSONL 영속성 (Pi 완전 동일)
│       │
│       ├── core/                        # Layer 3: Application Core (Pi: pi-coding-agent/core)
│       │   ├── session.py               # AgentSession — 모든 레이어 연결 중추
│       │   ├── policy/
│       │   │   ├── pipeline.py          # SecurityPipeline 오케스트레이터
│       │   │   ├── validator.py         # Step 1: 입력 검증
│       │   │   ├── authenticator.py     # Step 2: 인증 (API key/JWT)
│       │   │   ├── policy.py            # Step 3: 권한 기반 접근 통제
│       │   │   └── sandbox.py           # Step 4: 실행 샌드박스 + Human-in-the-loop
│       │   ├── tools/
│       │   │   ├── registry.py          # ToolRegistry (CRUD + 자동 발견)
│       │   │   ├── loader.py            # 파일 기반 툴 로더 (Python/YAML)
│       │   │   └── builtin/
│       │   │       ├── bash.py
│       │   │       ├── read_file.py
│       │   │       └── web_search.py
│       │   ├── skills/
│       │   │   ├── registry.py          # SkillRegistry
│       │   │   └── loader.py            # ~/.jarvis/skills/ 발견
│       │   └── plugins/
│       │       ├── protocol.py          # JarvisPlugin Protocol (훅 포인트)
│       │       ├── runner.py            # PluginRunner
│       │       └── loader.py            # ~/.jarvis/plugins/ 동적 로딩
│       │
│       └── ui/                          # Layer 4: Interface (Pi: pi-tui + pi-web-ui)
│           ├── protocol.py              # UIAdapter Protocol
│           ├── tui/
│           │   ├── app.py               # Textual App (JarvisTUI)
│           │   └── components/          # Chat, Input, Status 위젯
│           └── web/                     # 향후 FastAPI WebUI
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── faux_provider.py             # 테스트용 가짜 LLM (실 API 호출 없음)
│
└── docs/
    └── analysis/
        ├── pi-reference.md
        └── jarvis-architecture.md       # 이 파일
```

---

## 의존성 방향 (Hard Constraint)

```
config  ←  모든 레이어가 읽음 (역방향 불가)

ai  ←  agent  ←  core  ←  ui
```

- `ai`: 다른 내부 모듈 import 불가
- `agent`: `ai`만 import
- `core`: `ai`, `agent`만 import
- `ui`: 모든 레이어 import 가능
- `config`: 모든 레이어에서 단방향 읽기만 허용

---

## 핵심 타입 (`jarvis/ai/types.py`)

```python
# Pi의 Message Union 동일 패턴
Message = UserMessage | AssistantMessage | ToolResultMessage

# Pi의 AssistantMessageEvent 동일 패턴
StreamEvent = Union[
    TextDeltaEvent,       # {"type": "text_delta", "delta": str}
    ThinkingDeltaEvent,   # {"type": "thinking_delta", "thinking": str}
    ToolCallDeltaEvent,   # {"type": "tool_call_delta", ...}
    StopEvent,            # {"type": "stop", "reason": StopReason}
    UsageEvent,           # {"type": "usage", "usage": Usage}
    ErrorEvent,           # {"type": "error", "message": str}
]

# Pi의 ProviderStreamFn Protocol
class ProviderStreamFn(Protocol):
    def __call__(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None
    ) -> AsyncIterator[StreamEvent]: ...
```

---

## 보안 파이프라인 (강제 4단계)

Agent loop 진입 **이전에** 반드시 통과. 순서 변경 불가, 구현체만 교체 가능.

```
UserInput
    │
    ▼
[Step 1] InputValidator      → ValidatedInput   | ValidationError
    │
    ▼
[Step 2] Authenticator       → AuthContext      | AuthError
    │
    ▼
[Step 3] PolicyEngine        → PolicyResult     | PolicyDenied
    │
    ▼
[Step 4] Sandbox             → ApprovalResult   | SandboxBlocked
    │
    ▼
AgentSession.run(...)
```

| 단계 | 파일 | 역할 |
|------|------|------|
| 1. InputValidator | `core/security/validator.py` | 길이/패턴 검증, XSS 방어, 인코딩 정규화 |
| 2. Authenticator | `core/security/authenticator.py` | API key/JWT 검증, 사용자 식별 |
| 3. PolicyEngine | `core/security/policy.py` | 역할 기반 툴/스킬 접근 통제 |
| 4. Sandbox | `core/security/sandbox.py` | 위험 명령 차단, Human-in-the-loop 승인 |

---

## 메모리 미들웨어 체인

각 stage는 독립적이고 교체 가능. Pi의 `transformContext` 패턴.

```
MemoryMiddlewareChain
  └── stages: list[MemoryMiddleware]
       ├── WindowMemory       (최근 N개 유지)
       ├── CompactionMiddleware (Pi: compact() — 오래된 메시지 요약)
       ├── SqliteMemory        (영속 저장 + 검색)
       └── ExternalDBMemory   (벡터 DB 어댑터)
```

```python
class MemoryMiddleware(Protocol):
    async def transform(self, messages: list[Message], context: dict) -> list[Message]: ...
    async def store(self, message: Message, context: dict) -> None: ...
    async def retrieve(self, query: str, context: dict) -> list[Message]: ...
```

---

## 툴 레지스트리

Pi의 `AgentTool` + `SkillsManager` 패턴.

```python
class ToolRegistry:
    def register(self, tool: JarvisTool) -> None: ...   # first-wins
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> JarvisTool | None: ...
    def list_all(self) -> list[JarvisTool]: ...
    async def load_from_directory(self, path: str) -> list[str]: ...
    async def watch(self, path: str) -> None: ...       # watchfiles 핫리로드
```

**사용자 툴 정의 방식 (2가지):**

```yaml
# ~/.jarvis/tools/my_tool.yaml (선언형)
name: web-search
description: "Search the web"
execution_mode: parallel
parameters:
  type: object
  properties:
    query: {type: string}
  required: [query]
```

```python
# ~/.jarvis/tools/my_tool.py (명령형)
async def execute(tool_call_id: str, params: dict, **kwargs) -> dict:
    ...
```

---

## 플러그인 시스템

Pi의 Extension/ExtensionRunner 패턴. 각 훅은 Optional(구현 안 해도 no-op).

```python
class JarvisPlugin(Protocol):
    name: str
    version: str

    async def before_agent_start(self, prompt: str, context: dict) -> HookResult | None: ...
    async def before_tool_call(self, tool_name: str, args: dict, auth: AuthContext) -> HookResult | None: ...
    async def after_tool_call(self, tool_name: str, args: dict, result: dict) -> HookResult | None: ...
    async def on_message_end(self, message: Message) -> Message | None: ...
    async def transform_context(self, messages: list[Message]) -> list[Message] | None: ...
```

---

## 설정 계층 (`jarvis/config.py`)

최상위에서 모든 환경변수 관리. `JARVIS__LLM__API_KEY` 형식으로 오버라이드.

```python
class JarvisSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        env_file=".env",
    )

    llm: LLMProviderConfig       # provider, model, api_key, base_url
    security: SecurityConfig      # require_auth, allowed_roles, dangerous_commands
    memory: MemoryConfig          # backend, sqlite_path, window_size, compaction_threshold
    session: SessionConfig        # persistence_backend, sessions_dir
    ui: UIConfig                  # mode, theme
    plugin: PluginConfig          # plugins_dir, skills_dir, tools_dir, watch_files
    debug: bool = False
    log_level: str = "INFO"
```

---

## 전체 데이터 흐름

```
사용자 입력 (키보드)
        │
        ▼
┌─────────────────────┐
│       UI Layer      │  JarvisTUI (Textual)
│  InputBar submit    │
└────────┬────────────┘
         │ raw_input + credentials
         ▼
┌────────────────────────────────────────────────────┐
│                  AgentSession                       │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │           SecurityPipeline (강제)            │  │
│  │  [1] InputValidator → ValidatedInput         │  │
│  │  [2] Authenticator  → AuthContext            │  │
│  │  [3] PolicyEngine   → PolicyResult           │  │
│  │  [4] Sandbox        → ApprovalResult         │  │
│  └──────────────────────────────────────────────┘  │
│         │                                           │
│         ▼                                           │
│  PluginRunner.emit_before_agent_start()            │
│         │                                           │
│         ▼                                           │
│  ┌──────────────────────────────────────────────┐  │
│  │              Agent Layer                     │  │
│  │  MemoryChain.transform(messages)             │  │
│  │  run_agent_loop()                            │  │
│  │    ├─ stream_assistant_response()            │  │
│  │    │    └─ ai.stream() → LLM HTTP/SDK        │  │
│  │    └─ execute_tool_calls()                   │  │
│  │         ├─ PluginRunner.before_tool_call()   │  │
│  │         ├─ Sandbox.approve(command)          │  │
│  │         └─ ToolRegistry.get(name).execute()  │  │
│  └──────────────────────────────────────────────┘  │
│         │                                           │
│         ▼                                           │
│  SessionRepo.append()  [JSONL / SQLite]            │
└────────┬───────────────────────────────────────────┘
         │ AgentEvent stream
         ▼
┌─────────────────────┐
│       UI Layer      │  on_agent_event() → 위젯 갱신
│  ChatHistory update │
│  Thinking indicator │
└─────────────────────┘
```

---

## 세션 영속성 (JSONL — Pi 완전 동일)

```
# 한 줄 = JSON 객체, append-only, git-friendly
{"id": "uuid", "parent_id": "uuid|null", "timestamp": 1234567890,
 "type": "message|branch|compaction", "content": {...}}
```

브랜칭은 `parent_id`로 트리 구조. 새 파일 생성 없이 인라인 브랜칭.

---

## 구현 순서 (Phase별)

### Phase 1 — Foundation
1. `config.py` — Pydantic Settings (모든 모듈 필요)
2. `ai/types.py` — 핵심 타입
3. `ai/providers/base.py` + `faux_provider.py` (테스트용)
4. `ai/providers/anthropic.py`
5. `ai/stream.py`

### Phase 2 — Agent Core
6. `agent/types.py`
7. `agent/memory/protocol.py` + `in_memory.py`
8. `agent/session/jsonl.py`
9. `agent/loop.py`
10. `agent/harness.py`

### Phase 3 — Application Core (보안 우선)
11. `core/security/` — pipeline.py + 4개 컴포넌트 (완전 완성 후 다음 단계)
12. `core/tools/registry.py` + builtin tools
13. `core/plugins/` — protocol.py + runner.py
14. `core/skills/registry.py`
15. `core/session.py` — 전체 연결

### Phase 4 — UI
16. `ui/protocol.py`
17. `ui/tui/app.py` (Textual)

---

## 핵심 설계 결정

| 결정 | 선택 | 이유 |
|------|------|------|
| LLM 추상화 | litellm + 자체 ai/ 레이어 | litellm은 내부에서만, 외부 API는 자체 타입으로 래핑 |
| 스트리밍 | `AsyncIterator[StreamEvent]` | Pi의 `AsyncIterable<AssistantMessageEvent>` 완전 동일 |
| 메모리 | 미들웨어 체인 | 교체 가능 + 다단계 처리 (요약 → 필터 → 주입) |
| 보안 | 4단계 강제 순서, 교체 가능 구현체 | 순서 불변, 구현체만 교체 |
| 툴 로딩 | Python 파일 + YAML 선언 병용 | 사용자 친화적, Pi skills 패턴 동일 |
| 세션 | JSONL append-only 트리 | Pi 완전 동일, git-friendly |
| 비동기 | asyncio + anyio | Textual이 asyncio 기반 |
| 설정 | Pydantic Settings + .env | 중첩 설정, 타입 안전, 환경변수 오버라이드 |
