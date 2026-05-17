# Pi Agent Harness — Reference Analysis

> **Source:** `_reference/pi/`
> **Analyzed:** 2026-05-17
> **Version:** 0.74.1 (Earendil Works)

Pi는 오픈소스 미니멀 터미널 코딩 에이전트 하네스. "Pi에 맞추는 게 아니라 Pi를 내 워크플로우에 맞게 바꿔 쓴다"는 철학. 4가지 실행 모드(TUI, Print/JSON, RPC, SDK)와 TypeScript 익스텐션 시스템을 통한 확장성이 핵심.

---

## 기술 스택

| 항목 | 내용 |
|------|------|
| 언어 | TypeScript 5.9.2 (strict, ESM) |
| 런타임 | Node.js ≥20.0.0 |
| 패키지 관리 | npm workspaces (모노레포, lockstep 버전) |
| 린팅/포매팅 | Biome 2.3.5 (tab 3칸, 120자 줄 너비) |
| 스키마 검증 | TypeBox 1.1.24 |
| 테스트 | Vitest 3.2.4 |
| 멀티 LLM | Anthropic, OpenAI, Google, Mistral, AWS Bedrock 등 25+ |

---

## 패키지 구조

```
packages/
├── ai/            — @earendil-works/pi-ai
├── agent/         — @earendil-works/pi-agent-core
├── coding-agent/  — @earendil-works/pi-coding-agent (CLI 메인)
├── tui/           — @earendil-works/pi-tui
└── web-ui/        — @earendil-works/pi-web-ui
```

**빌드 의존 순서:** `tui → ai → agent → coding-agent → web-ui`

---

## 패키지별 역할

### `pi-ai` — 멀티 프로바이더 LLM API

- 25+ LLM 프로바이더를 단일 인터페이스로 통합
- 모든 호출은 `AsyncIterable<AssistantMessageEvent>` 스트림 반환
- 스트림 이벤트: `text_delta`, `thinking_delta`, `toolcall_delta`, `stop`, `usage`, `error`
- 프롬프트 캐싱, OAuth, 이미지 I/O 지원
- `models.generated.ts`는 자동 생성 파일 — **직접 수정 금지**, `generate-models.ts` 수정 후 재생성

**핵심 파일:**
- `src/types.ts` — `Api`, `Provider`, `Model<T>`, `Message`, `Tool` 타입
- `src/stream.ts` — 메인 스트리밍 진입점
- `src/providers/register-builtins.ts` — 프로바이더 lazy 로딩
- `src/env-api-keys.ts` — 환경변수에서 API 키 읽기

### `pi-agent-core` — 에이전트 코어

- `pi-ai` 위에 상태 관리(메시지 히스토리, 툴, 세션 컨텍스트) 추가
- 이벤트 기반: `agent_start`, `turn_start`, `message_update`, `tool_execution_start`, `agent_end`
- 툴 실행 모드: `parallel`(기본) / `sequential`
- 세션 저장: JSONL 포맷 (git-friendly, 브랜치 트리 구조)
- 컴팩션: 컨텍스트 오버플로우 시 오래된 메시지 자동 요약

**핵심 파일:**
- `src/agent.ts` — `Agent` 클래스
- `src/agent-loop.ts` — 턴 로직 (LLM 호출 → 툴 실행 → 반복)
- `src/harness/agent-harness.ts` — 세션, 컴팩션, 프롬프트 빌딩 포함한 확장 에이전트
- `src/harness/session/jsonl-repo.ts` — JSONL 세션 영속성

### `pi-coding-agent` — CLI 애플리케이션

- 4가지 실행 모드: Interactive TUI, Print/JSON, RPC, SDK
- 내장 툴 7개: `read`, `write`, `edit`, `bash`, `find`, `grep`, `ls`
- 익스텐션 시스템: `~/.pi/extensions/*.ts` 런타임 로드
- Skills: JSON 툴 정의 + Markdown 문서
- Prompt Templates: `/pr <url>` 형태 Markdown 매크로
- 세션 브랜칭/내보내기(HTML) 지원

**핵심 파일:**
- `src/core/agent-session.ts` — 모든 모드를 연결하는 중추
- `src/core/agent-session-runtime.ts` — 툴 실행 루프, 메시지 큐잉
- `src/core/extensions/runner.ts` — 익스텐션 훅 실행
- `src/modes/` — 4가지 모드 구현체

### `pi-tui` — 터미널 UI 라이브러리

- **차분 렌더링**: 변경된 영역만 다시 그리기 (3-strategy 시스템)
- CSI 2026 synchronized output으로 깜빡임 없는 화면 갱신
- 컴포넌트: Text, Input, Editor, Markdown, Loader, SelectList 등 13개
- 외부 TUI 라이브러리 미사용 (순수 Node.js)

### `pi-web-ui` — 웹 UI

- Web Components (mini-lit) + Tailwind CSS v4
- `ChatPanel` — 완성형 채팅 인터페이스
- IndexedDB 기반 세션/설정 저장
- Ollama, LM Studio, vLLM 등 로컬 모델 지원

---

## 아키텍처 레이어

```
UI 모드 (TUI / RPC / Print / SDK)
         ↓
AgentSession        ← 세션 영속성, 익스텐션 훅, 이벤트 버스
         ↓
Agent + AgentLoop   ← 상태 관리, 툴 실행 루프
         ↓
stream()            ← 프로바이더별 구현
         ↓
LLM HTTP/SDK
```

---

## 핵심 설계 패턴

### 스트리밍 이벤트 통합

모든 LLM 호출은 `AsyncIterable<AssistantMessageEvent>` 반환. 25+ 프로바이더가 동일한 이벤트 포맷으로 정규화됨.

```
start → text_start → text_delta* → text_end
                   → thinking_delta*
                   → toolcall_start → toolcall_delta* → toolcall_end
     → done / error
```

### 메시지 타입 시스템

```typescript
type Message =
  | { role: 'user',       content: TextContent[] | ImageContent[] }
  | { role: 'assistant',  content: (TextContent | ToolCall)[] }
  | { role: 'toolResult', toolCallId, toolName, content, isError }
```
- `convertToLlm()` — UI 전용 메시지 필터링 후 LLM 전달

### 세션 영속성 (JSONL 트리)

```
{ id, parentId, timestamp, type: 'message' | 'branch', content }
```
- 한 파일 내에서 브랜칭 (`parentId`로 트리 구성)
- git에서 diff/merge 가능한 구조

### 툴 실행 모드

- **Parallel (기본)**: preflight는 순차, 실행은 동시
- **Sequential**: 사이드이펙트가 있는 툴에 적합
- 툴별 `executionMode: "sequential"` 오버라이드 가능

### 익스텐션 훅 포인트

```
beforeToolCall → tool execution → afterToolCall
turnStart → agentLoop → turnEnd
```
`~/.pi/extensions/*.ts`에 TypeScript 플러그인으로 커스터마이징.

---

## 설정 파일

### `biome.json`

```json
{
  "formatter": { "indentStyle": "tab", "indentWidth": 3, "lineWidth": 120 },
  "linter": {
    "rules": {
      "style": { "noNonNullAssertion": "off", "useConst": "error" },
      "suspicious": { "noExplicitAny": "off" }
    }
  }
}
```

### `tsconfig.base.json`

```json
{
  "target": "ES2022",
  "module": "Node16",
  "moduleResolution": "Node16",
  "strict": true
}
```

### 런타임 설정 (`~/.pi/agent/`)

```
settings.json   — thinking level, model, transport, theme
auth.json       — API 키 / OAuth 토큰 (절대 커밋 금지)
keybindings.json — 키 바인딩 커스터마이징
sessions/       — JSONL 세션 파일
extensions/     — 커스텀 플러그인
prompts/        — 커스텀 프롬프트 템플릿
skills/         — 커스텀 툴 정의
```

---

## 주요 커맨드

```bash
# 빌드
npm run build              # 전체 빌드 (의존 순서대로)

# 품질 검사 (커밋 전 필수)
npm run check              # Biome lint + tsgo 타입 체크

# 테스트
npm test                   # Vitest 전체 실행
./test.sh                  # API 키 없이 테스트 (권장)

# 개발
npm run dev                # 전체 패키지 watch 모드
./pi-test.sh               # 소스에서 직접 pi 실행
./pi-test.sh --no-env      # API 키 없이 실행

# 릴리즈
npm run release:patch      # 버그/기능 수정
npm run release:minor      # API 브레이킹 변경
```

---

## AGENTS.md 핵심 규칙

에이전트(및 기여자)가 이 레포에서 작업할 때 지켜야 할 규칙들.

### 코드 규칙

- 광범위한 변경 전 파일 전체를 반드시 읽을 것
- `any` 타입 최대한 지양
- 인라인 `await import()` 금지
- 타입 에러를 코드 삭제로 해결하지 말 것 — 의존성 업그레이드로 해결
- 키바인딩은 항상 `DEFAULT_*` 객체에 추가 (하드코딩 금지)

### Git 규칙 (병렬 에이전트 안전)

- `git add -A` / `git add .` **절대 금지**
- 반드시 `git add <specific-file>` 으로 본인 파일만 스테이징
- **금지 명령:** `git reset --hard`, `git checkout .`, `git clean -fd`, `git stash`, `git commit --no-verify`
- 커밋 전 `git status`로 스테이징 파일 확인

### 테스트 규칙

- 실제 LLM API 호출 없는 faux 프로바이더 사용
- 회귀 테스트: `test/suite/regressions/<issue-number>-<slug>.test.ts`
- 테스트 생성/수정 후 반드시 실행해서 통과 확인

---

## 새 LLM 프로바이더 추가 체크리스트

`pi-ai` 패키지 (7단계):
1. `src/types.ts` — `Api`, `KnownProvider` 타입 추가
2. `src/providers/your-provider.ts` — `streamYourProvider()` 구현
3. `package.json` — subpath export 추가
4. `src/providers/register-builtins.ts` — lazy 등록
5. `src/env-api-keys.ts` — 환경변수 키 감지 추가
6. `scripts/generate-models.ts` — 모델 목록 fetch 추가
7. `test/stream.test.ts` — 테스트 추가

`coding-agent` 패키지 (5단계):
1. `src/core/model-resolver.ts` — 기본 모델 추가
2. `src/core/provider-display-names.ts` — UI 레이블
3. `src/cli/args.ts` — 환경변수 문서화
4. `README.md` — 설정 안내 추가
5. `docs/providers.md` — 프로바이더 가이드 추가

---

## 릴리즈 프로세스

모든 패키지가 동일 버전(lockstep). `npm run release:patch` 실행 시:

1. 미커밋 변경사항 확인
2. 모든 패키지 버전 일괄 bump
3. 각 패키지 `CHANGELOG.md`의 `[Unreleased]` → `[x.y.z] - YYYY-MM-DD`
4. 커밋 + 태그
5. npm 퍼블리시
6. 새 `[Unreleased]` 섹션 추가
7. origin push

**Changelog 섹션 순서:** Breaking Changes → Added → Changed → Fixed → Removed
