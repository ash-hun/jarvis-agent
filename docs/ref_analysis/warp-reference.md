# Warp Reference Analysis

Source: `_reference/warp/` (Warp open-source client, AGPL v3 + MIT)

---

## 1. 프로젝트 개요

Warp는 **Rust 기반 Agentic Development Environment**로, 터미널 에뮬레이터에서 출발해 AI 에이전트 워크플로우 플랫폼으로 확장된 제품이다. OpenAI가 founding sponsor이며 GPT 모델로 에이전트 워크플로우를 구동한다.

주요 특징:
- 자체 UI 프레임워크(WarpUI) — Flutter 영감을 받은 Element/View/Handle 패턴
- 에이전트 모드(Oz) — 코드베이스 인덱싱, 코드 리뷰, 스펙 작성, PR 생성 자동화
- Warp Drive — 워크플로우, 노트북, 세션 설정의 클라우드 동기화
- 멀티플랫폼 — macOS, Windows, Linux, WASM 타겟 동시 지원

라이선스: UI 프레임워크(`warpui_core`, `warpui`) = MIT, 나머지 = AGPL v3

---

## 2. 아키텍처

### 2.1 레이어 구조

```
app/                    # 메인 바이너리 (terminal, AI, auth, settings, workspace)
├── src/
│   ├── terminal/       # 터미널 에뮬레이션 + 셸 관리
│   ├── ai/             # Agent Mode, 오케스트레이션, 이벤트 폴러
│   ├── drive/          # Warp Drive 클라우드 동기화
│   ├── auth/           # 인증 + 사용자 관리
│   ├── settings/       # 설정 + 환경 설정
│   └── workspace/      # 세션 + 워크스페이스 관리

crates/                 # 60+ 독립 크레이트
├── warpui/             # 커스텀 UI 프레임워크 (MIT)
├── warpui_core/        # UI 핵심 추상화 (MIT)
├── ai/                 # AI/LLM 인터페이스
├── editor/             # 텍스트 편집 기능
├── warp_completer/     # 자동완성
├── warp_terminal/      # 터미널 프리미티브
├── persistence/        # Diesel ORM + SQLite
├── graphql/            # GraphQL 클라이언트 + 스키마
├── ipc/                # 프로세스 간 통신
├── remote_server/      # 원격 실행 서버
└── ...
```

### 2.2 WarpUI Entity-Handle 패턴

WarpUI의 핵심 설계 원칙:

```rust
// Global App이 모든 View/Model(Entity)을 소유
// View는 다른 View를 직접 소유하지 않고 ViewHandle<T>로 참조
// AppContext가 렌더/이벤트 처리 중 핸들에 임시 접근을 제공

App (global)
├── owns all entities (views, models)
├── ViewHandle<T> → indirect reference (not ownership)
└── AppContext → temporary access during render/events
```

주요 규칙:
- `MouseStateHandle`은 생성 시 한 번만 만들어야 함 — 렌더링 중 인라인 생성 시 마우스 입력이 동작하지 않음
- `TerminalModel.lock()` 중첩 호출 금지 — 데드락 및 UI freeze 유발
- context 파라미터(`AppContext`, `ViewContext`, `ModelContext`)는 항상 `ctx`로 명명하고 마지막에 위치

### 2.3 의존성 기술 스택

| 역할 | 라이브러리 |
|------|-----------|
| 비동기 런타임 | Tokio |
| GPU 렌더링 | wgpu (Metal/DX12/Vulkan/OpenGL ES) |
| HTTP 클라이언트 | reqwest |
| DB ORM | Diesel (SQLite) |
| GraphQL | cynic |
| 터미널 파싱 | vte (Warp fork) |
| 시리얼라이제이션 | serde/serde_json |
| 에러 처리 | anyhow/thiserror |
| 폰트 | font-kit (Warp fork) |
| 파서 콤비네이터 | nom |
| 트리-시터 | arborium (22개 언어) |
| 메모리 할당자 | jemalloc |
| 창 시스템 | winit (Warp fork) |
| MCP | rmcp (Warp fork) |

---

## 3. AI/Agent 아키텍처

### 3.1 에이전트 오케스트레이션 (Oz)

```
AgentConversation (SQLite 영속)
├── parent_conversation_id    # 부모 에이전트 추적
├── run_id                    # 서버 side Task ID
└── last_event_sequence       # 중복 없는 이벤트 전달을 위한 커서

OrchestrationEventPoller
├── watched_run_ids           # 모니터링할 자식 run_id 집합
├── event_cursor              # per-conversation i64 시퀀스 번호
└── handle_poll_result()      # SSE/폴링 이벤트 배치 처리

이벤트 흐름:
BlocklistAIHistoryModel → RestoredConversations event
  → OrchestrationEventPoller (커서 복원, watched_run_ids 복원)
  → start_event_delivery() (SSE/폴링 시작)
  → persist_cursor() (SQLite + 서버에 커서 저장)
```

### 3.2 에이전트 루프 패턴

Warp의 에이전트는 **스펙 → 구현 → 검증** 사이클로 운영된다. 이 패턴은 `_reference/warp/.agents/skills/`에 코드화되어 있다.

---

## 4. 스펙 주도 개발 워크플로우 (핵심 참고)

Warp에서 가장 주목할 만한 패턴은 **에이전트가 스스로 스펙을 작성하고 구현하는 spec-driven workflow**이다.

### 4.1 디렉토리 구조

```
specs/
├── APP-1234/
│   ├── PRODUCT.md    # 사용자 관점 행동 명세 (Behavior invariants)
│   └── TECH.md       # 구현 계획 + 테스트 전략
├── GH371/
│   ├── product.md
│   └── tech.md
└── feature-slug/
    ├── PRODUCT.md
    └── TECH.md
```

### 4.2 PRODUCT.md 구조

```markdown
# Feature Name

## Summary
1-3문장 요약

## Behavior
번호가 매겨진 테스트 가능한 불변식(invariant) 목록:
1. 기본 동작
2. 상태 전환
3. 엣지 케이스 (권한 거부, 오프라인, 타임아웃, 경쟁 조건)
4. 키보드/접근성 동작
5. 회귀하지 않아야 할 불변식

## (Optional) Problem / Goals / Non-goals / Figma
```

PRODUCT.md에는 **검증/테스트 섹션 없음** — 그건 TECH.md의 역할.

### 4.3 TECH.md 구조

```markdown
# Feature — Tech Spec

## Context
현재 코드베이스 상태, 관련 파일 + 라인 레퍼런스
(구현 전에 코드를 실제로 읽고 작성)

## Proposed Changes
모듈별 변경 계획, 새 타입/API/상태, 데이터 흐름, 트레이드오프

## Testing and Validation
PRODUCT.md의 Behavior invariant 번호를 직접 참조하여
각 불변식마다 구체적인 테스트 또는 검증 단계 매핑

## (Optional) End-to-end flow / Diagram / Risks / Parallelization / Follow-ups
```

### 4.4 스킬 체인 (`.agents/skills/`)

| 스킬 | 역할 |
|------|------|
| `write-product-spec` | PRODUCT.md 작성 |
| `write-tech-spec` | TECH.md 작성 (코드베이스 실제 조사 후) |
| `spec-driven-implementation` | 전체 워크플로우 조율 |
| `implement-specs` | 승인된 스펙에서 코드 구현 |
| `rust-unit-tests` | 단위 테스트 작성/실행 |
| `triage-issue-local` | 이슈 트리아지 (저장소별 커스터마이즈) |
| `review-pr` | PR 리뷰 |
| `create-pr` | PR 생성 |
| `add-feature-flag` | 피처 플래그 추가 |
| `diagnose-ci-failures` | CI 실패 분석 |
| `resolve-merge-conflicts` | 머지 충돌 해결 |
| `warp-integration-test` | 통합 테스트 |

---

## 5. 피처 플래그 시스템

```rust
// crates/warp_core/src/features.rs (app/src/features.rs에서 re-export)
#[derive(Sequence)]
pub enum FeatureFlag {
    YourNewFeature,
    OrchestrationV2,
    // ...
}

// 단계별 출시
pub const DOGFOOD_FLAGS: &[FeatureFlag] = &[...];   // 내부 dogfood
pub const PREVIEW_FLAGS: &[FeatureFlag] = &[...];   // 미리보기
pub const RELEASE_FLAGS: &[FeatureFlag] = &[...];   // 정식 출시

// 사용법
if FeatureFlag::YourNewFeature.is_enabled() { ... }
```

원칙:
- 컴파일 타임 `#[cfg(...)]`보다 런타임 플래그 선호 → 재컴파일 없이 토글 가능
- 플래그는 고수준 제품 관점으로 유지 (call-site별 플래그 금지)
- 출시 안정화 후 플래그와 dead branch 제거

---

## 6. 테스트 전략

### 6.1 단위 테스트

```
tests 파일 위치: ${filename}_tests.rs 또는 mod_test.rs
파일 끝에 include:
  #[cfg(test)]
  #[path = "filename_tests.rs"]
  mod tests;
```

WarpUI 테스트 패턴:
```rust
App::test((), |mut app| async move {
    initialize_app_for_terminal_view(&mut app);
    let term = add_window_with_terminal(&mut app, None);
    term.update(&mut app, |view, _ctx| { ... });
    term.read(&app, |view, _ctx| { assert!(...) });
})
```

### 6.2 테스트 실행

```bash
cargo nextest run --no-fail-fast --workspace --exclude command-signatures-v2
cargo nextest run -p <crate_name>                     # 특정 크레이트
cargo nextest run -E 'test(<substring>)'              # 특정 테스트
cargo test --doc                                       # doc tests
```

### 6.3 주요 테스트 헬퍼

| 헬퍼 | 역할 |
|------|------|
| `TerminalModel::mock()` | 터미널 모델 목 |
| `.simulate_block()` | 커맨드 블록 시뮬레이션 |
| `VirtualFS::test()` | IO 테스트용 가상 파일시스템 |
| `FeatureFlag::X.override_enabled()` | 테스트 내 플래그 토글 |

---

## 7. 빌드 프로파일

| 프로파일 | 용도 |
|----------|------|
| `dev` | 개발 (line-tables debuginfo, unpacked split) |
| `release` | 배포 (line-tables, packed dSYM) |
| `release-lto` | ThinLTO 릴리즈 (최고 성능) |
| `release-cli` | Oz CLI tarball (크기 최적화, opt-level=s) |
| `release-wasm` | WASM 타겟 |
| `dev-remote` | 원격 서버 배포 (심볼 strip으로 rsync 효율화) |

---

## 8. DB 레이어

- **ORM**: Diesel (SQLite)
- **마이그레이션**: `crates/persistence/migrations/`
- **스키마**: `crates/persistence/src/schema.rs`

---

## 9. GraphQL 레이어

- 스키마: `crates/warp_graphql_schema/api/schema.graphql`
- 클라이언트 코드 생성: cynic
- WebSocket GraphQL (`/graphql/v2`) + HTTP REST 혼용

---

## 10. Jarvis 프로젝트에의 시사점

### 채택할 패턴

1. **스펙 주도 개발**: `specs/<ticket>/PRODUCT.md` + `TECH.md` 패턴
   - Behavior를 번호가 매겨진 invariant 목록으로 작성
   - TECH.md는 코드베이스를 실제 조사한 후 라인 레퍼런스 포함하여 작성
   - 구현이 스펙에서 이탈하면 스펙을 먼저 업데이트

2. **에이전트 스킬 체계**: `.agents/skills/<skill-name>/SKILL.md`
   - 에이전트 스스로 실행 가능한 재사용 가능 워크플로우
   - 저장소별 커스터마이즈 가능 (triage-issue-local 예시)

3. **피처 플래그**: 런타임 체크 선호, 출시 후 정리
   - Jarvis의 provider registry 패턴과 유사한 확장 포인트

4. **테스트 격리**: 테스트 파일 분리 (`_tests.rs`), 의존성 주입
   - Jarvis의 `FauxProvider` 패턴과 유사

### 차이점

| 측면 | Warp (Rust) | Jarvis (Python) |
|------|-------------|-----------------|
| UI 프레임워크 | 자체 WarpUI (GPU 렌더) | Textual (터미널 TUI) |
| 비동기 | Tokio | asyncio |
| DB | Diesel/SQLite | SQLite (aiosqlite) |
| AI 통합 | 자체 Oz 에이전트 + 외부 CLI | 멀티프로바이더 LLM 추상화 |
| 스펙 관리 | specs/ 디렉토리 | docs/analysis/ (현재) |
| 테스트 격리 | FauxProvider 패턴 없음 | FauxProvider 자체 구현 |
