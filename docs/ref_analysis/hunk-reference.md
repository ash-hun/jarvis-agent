# Hunk Reference Analysis

> **Date:** 2026-05-17  
> **Source:** `_reference/hunk/`  
> **Purpose:** TUI 개편을 위한 레퍼런스 분석

---

## 1. 프로젝트 개요

**Hunk**는 에이전트가 작성한 코드 변경사항을 리뷰하기 위한 터미널 diff 뷰어.

- **목표**: "모던 데스크탑 diff 도구의 터미널 버전"
- **핵심 철학**: 리뷰 우선 아키텍처 — 메인 패널은 모든 파일 diff의 단일 스트림
- **사이드바**: 파일 네비게이션 (메인 패널을 단일 파일로 축소하지 않음)
- **레이아웃**: `split`, `stack`, `auto` (반응형) 지원
- **에이전트 제어**: 에이전트는 TUI를 직접 제어하지 않고 CLI 세션 명령 사용

---

## 2. 패키지 구조

```
src/
├── core/          CLI 파싱, 설정 레이어, VCS 통합, 타입 정의
├── ui/            React/OpenTUI 컴포넌트, 상태 관리, 테마
│   ├── App.tsx        메인 오케스트레이션 셸
│   ├── components/    재사용 패널/크롬 컴포넌트
│   ├── hooks/         상태 훅 (useReviewController, useMenuController)
│   ├── lib/           순수 헬퍼 (reviewState, sidebar, hunks, layouts)
│   └── diff/          Pierre diff 렌더링 파이프라인
├── hunk-session/  데몬 세션 타입 및 브릿지
├── session/       세션 CLI 명령 실행
└── session-broker/ 클라이언트 데몬 연결 관리

packages/
├── session-broker-core   공유 세션 브로커 프로토콜 타입
├── session-broker        범용 브로커 연결 로직
├── session-broker-bun    Bun 소켓 구현
└── session-broker-node   Node.js 소켓 구현

skills/hunk-review/SKILL.md   에이전트용 스킬 정의
```

---

## 3. UI 프레임워크 및 컴포넌트

**프레임워크**: OpenTUI (`@opentui/core`) — React 기반 터미널 UI

### 컴포넌트 계층

```
<AppHost>                     세션 리로드 래퍼
└── <App>                     오케스트레이션 셸
    ├── <MenuBar>             상단 크롬
    ├── <StatusBar>           하단 크롬
    ├── <SidebarPane>         파일 목록 + 네비게이션
    │   └── <FileListItem>*   클릭 가능한 파일 항목
    ├── <PaneDivider>         리사이즈 드래그 핸들
    └── <DiffPane>            메인 리뷰 스트림
        ├── <DiffSection>*    파일당 하나
        │   └── <PierreDiffView>  diff 렌더링
        │       ├── <DiffFileHeaderRow>
        │       ├── Diff rows (split/stack 레이아웃)
        │       └── <AgentInlineNote>*  인라인 어노테이션
        └── <VerticalScrollbar>
```

### 레이아웃 치수

```
SIDEBAR_MIN_WIDTH = 22 columns
DIFF_MIN_WIDTH    = 48 columns
BODY_PADDING      = 2
DIVIDER_WIDTH     = 1
DIVIDER_HIT_WIDTH = 5  (마우스 타겟 확대)
```

### split 모드 레이아웃

```
┌─────────────────────────────────────┐
│ MenuBar                             │
├──────────┬──────────────────────────┤
│ Sidebar  │ Main Diff Pane           │
│ (fixed)  │ (variable width)         │
│          │                          │
│ Files    │ • File 1                 │
│ + Nav    │   ├─ Hunk 1              │
│          │   └─ Hunk 2              │
│          │ • File 2                 │
├──────────┴──────────────────────────┤
│ StatusBar                           │
└─────────────────────────────────────┘
```

---

## 4. 상태 관리

### App 컴포넌트 소유 상태

| 상태 | 설명 |
|------|------|
| `layoutMode`, `themeId` | 레이아웃, 테마 |
| `showAgentNotes`, `wrapLines`, `showLineNumbers` | 표시 옵션 |
| `selectedFileId`, `selectedHunkIndex` | 선택 상태 (via useReviewController) |
| `focusArea` | 포커스 영역 (`files` / `filter` / `note`) |
| `resizeDragOriginX` | 사이드바 리사이즈 |

### useReviewController 훅 소유 상태

| 상태 | 설명 |
|------|------|
| `selectedFileId`, `selectedHunkIndex` | 현재 선택 |
| `filter`, `deferredFilter` | 검색 필터 (deferred = 성능 최적화) |
| `liveCommentsByFileId` | 에이전트 인라인 노트 |
| `userNotesByFileId` | 사용자 인라인 노트 |
| `visibleFiles`, `sidebarEntries` | 파생 상태 (useMemo) |
| `hunkCursors`, `annotatedHunkCursors` | 파생 상태 (useMemo) |

---

## 5. 이벤트 및 메시지 시스템

### 방향 1: 입력 → App

```
useKeyboard() / useRenderer()
  → useAppKeyboardShortcuts()  글로벌 단축키
  → useMenuController()        메뉴 조작
  → useReviewController()      선택 및 노트 액션
  → 직접 핸들러               스크롤, 리사이즈, 필터 포커스
```

### 방향 2: 세션 데몬 → App

```
HunkSessionServerMessage (WebSocket/소켓):
  "comment"          → reviewController.addLiveComment()
  "comment_batch"    → 배치 노트 추가
  "navigate_to_hunk" → reviewController.selectHunk()
  "reload_session"   → diff 교체
  "remove_comment"   → 노트 삭제
  "clear_comments"   → 전체 노트 삭제

응답: AppliedCommentResult (file, hunk, line, commentId)
```

### 방향 3: App → DiffPane

Props로 단방향 전달:
- `files`, `selectedFileId`, `selectedHunkIndex`
- `visibleAgentNotes`, `draftNote`
- Callback: `onStartUserNoteAtHunk(hunkIndex, target)`

---

## 6. 렌더링 파이프라인

```
1. Diff 파싱 & 정규화
   Git/jj/file → loadAppBootstrap() → Pierre 파싱 → Changeset { files: DiffFile[] }

2. 리뷰 상태 계산 (순수 함수, reviewState.ts)
   buildReviewState(files, liveComments, filter, selection)
     → visibleFiles, sidebarEntries, hunkCursors, annotatedHunkCursors

3. Diff 행 빌드 (PierreDiffView)
   buildSplitRows() / buildStackRows()
     → Pierre diff 엔진 + 신택스 하이라이팅
     → DiffRow[] (type, spans)

4. 인라인 노트 계획 (reviewRenderPlan.ts)
   buildReviewRenderPlan(rows, visibleAgentNotes, file)
     → PlannedReviewRow[] (diff rows + note 삽입 위치)

5. 가상 윈도잉 (성능 최적화)
   resolveVisiblePlannedRowWindow(plannedRows, scrollTop, viewportHeight)
     → 이진 탐색으로 가시 영역 행만 렌더링

6. React 렌더링
   <DiffPane> → <DiffSection> → <PierreDiffView> → 각 행

7. 터미널 렌더링 (OpenTUI)
   더티 트래킹 → 변경된 영역만 stdout 출력
```

---

## 7. 핵심 설계 패턴

### 1. Startup Planner 패턴

```typescript
type StartupPlan =
  | { kind: "help" }
  | { kind: "daemon-serve" }
  | { kind: "session-command"; input: SessionCommand }
  | { kind: "plain-text-pager" }
  | { kind: "static-diff-pager" }
  | { kind: "passthrough" }
  | { kind: "app"; bootstrap: AppBootstrap }
```

모든 CLI 입력을 렌더링 전에 7가지 결과 중 하나로 정규화.

### 2. Pure Derivation (순수 파생)

```typescript
// reviewState.ts — 프레임워크 의존성 없음, 테스트 가능
export function buildReviewState({ files, liveComments, filter, ... }) {
  return { visibleFiles, sidebarEntries, hunkCursors, ... }
}
// UI 렌더링, 세션 데몬 명령, 단위 테스트 모두 동일 함수 사용
```

### 3. Explicit Intent Encoding

```typescript
// 불리언 플래그 대신 명시적 의도 구조체:
interface ReviewSelectionOptions {
  alignFileHeaderTop?: boolean;  // 스크롤 요청
  preserveViewport?: boolean;    // 스크롤 유지
  scrollToNote?: boolean;        // 노트 위치로 이동
}
```

### 4. Session Bridge 패턴

```
데몬 프로토콜 ←→ 브릿지 (번역) ←→ UI 액션
  HunkSessionServerMessage → bridge.ts → reviewController.addLiveComment()
```

### 5. Stable Anchor 스크롤

```typescript
// 레이아웃 전환(split↔stack) 시 스크롤 위치 보존:
// 1. 현재 뷰포트의 기준 행 저장
// 2. 레이아웃 변경
// 3. 새 내용에서 기준 행을 찾아 동일 오프셋으로 복원
interface ViewportRowAnchor {
  row: PlannedReviewRow
  yOffset: number
}
```

### 6. Config Layering

```
Default → Global (~/.hunk/config.toml) → Repo (.hunk/config.toml) → Command section → CLI flags
```

---

## 8. Skills 통합 방식

에이전트가 TUI와 인터랙션하는 방법:

```bash
# 1. 현재 세션의 diff 구조 파악
hunk session review --repo . --json

# 2. 파일/헝크로 네비게이션
hunk session navigate --repo . --file src/App.tsx --hunk 2

# 3. 인라인 노트 추가
hunk session comment add --repo . --file README.md --new-line 103 --summary "..."

# 4. diff 교체
hunk session reload --repo . -- diff main...feature
```

**핵심 원칙**: 에이전트는 TUI에 직접 타이핑하지 않고 데몬에 CLI 명령을 전송.

---

## 9. Jarvis TUI 개편 시 참고 포인트

| Hunk 패턴 | Jarvis 적용 방향 |
|-----------|-----------------|
| `split` / `stack` 레이아웃 | Textual의 `Horizontal` / `Vertical` 컨테이너로 구현 |
| `MenuBar` + `StatusBar` 크롬 | Textual `Header` / `Footer` 확장 |
| `SidebarPane` (파일 네비) | Textual `ListView` 또는 `Tree` 위젯 |
| Pure derivation (`reviewState.ts`) | Python 순수 함수, 테스트 가능한 상태 계산 |
| `useReviewController` 훅 | `AgentSession` 메서드로 상태 집중 |
| Stable anchor 스크롤 | Textual `ScrollView.scroll_to()` + 앵커 추적 |
| Startup Planner | `main()` 진입점에서 모드 분기 |
| Session Bridge | 기존 `AgentSession.subscribe()` 이벤트 시스템 활용 |
| Config Layering | `JarvisSettings`에 이미 구현됨 |
| Virtual scrolling | Textual 내장 가상 스크롤 (`DataTable`, `ListView`) 활용 |

---

## 10. 핵심 파일 경로

```
_reference/hunk/src/ui/App.tsx                         메인 오케스트레이션
_reference/hunk/src/ui/lib/reviewState.ts              순수 상태 파생 (패턴 참고)
_reference/hunk/src/ui/hooks/useReviewController.ts    액션 디스패처
_reference/hunk/src/ui/diff/reviewRenderPlan.ts        인라인 노트 계획
_reference/hunk/src/hunk-session/bridge.ts             데몬 메시지 번역
_reference/hunk/src/core/config.ts                     설정 레이어링
_reference/hunk/CLAUDE.md                              아키텍처 규칙
```
