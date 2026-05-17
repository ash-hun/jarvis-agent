# Warp Agent Skills 분석

Source: `_reference/warp/.agents/skills/`

Jarvis가 참고할 수 있는 Warp의 에이전트 스킬 시스템 상세 분석.

---

## 1. 스킬 시스템 구조

### 디렉토리 레이아웃

```
.agents/skills/
├── <skill-name>/
│   ├── SKILL.md           # 스킬 본체 (항상 로드)
│   └── references/        # 선택적 참조 파일 (필요 시 로드)
│       ├── guide.md
│       └── examples.md
└── ...
```

### SKILL.md 프론트매터

```yaml
---
name: skill-name
description: "스킬이 하는 일과 언제 쓰는지를 구체적으로 기술"
specializes: parent-skill   # 선택: 코어 스킬 특화 시
---
```

### 로딩 전략 (컨텍스트 효율)

| 단계 | 로드 내용 | 시점 |
|------|-----------|------|
| 1 | name + description (메타데이터) | 항상 (시작 시) |
| 2 | SKILL.md 본문 | 스킬 트리거 시 |
| 3 | references/*.md | 필요 시에만 |

SKILL.md는 **150-200줄 이내** 유지. 초과 시 references/ 분리.

---

## 2. 각 스킬 상세

### 2.1 `spec-driven-implementation` — 전체 워크플로우 오케스트레이터

**트리거**: 상당한 기능 개발 시작, 에이전트 구동 구현 계획

**워크플로우 체인**:
```
1. 스펙 필요 여부 판단
   ↓
2. write-product-spec → PRODUCT.md
   ↓
3. (복잡도에 따라) write-tech-spec → TECH.md
   ↓
4. implement-specs (승인 후)
   ↓
5. 구현 중 스펙 최신화
   ↓
6. rust-unit-tests + 통합테스트로 검증
```

**스펙 필요 기준**:
- 1000+ LOC 예상 변경
- 제품/아키텍처 모호성 존재
- 스택 깊은 또는 교차 변경
- 회귀 비용이 높은 행동 변경

**스펙 불필요 기준**:
- 소규모 로컬 버그 수정
- 간단한 리팩토링
- 모호성 없는 좁은 UI 수정

---

### 2.2 `write-product-spec` — PRODUCT.md 작성

**핵심 원칙**:
- "User" = 해당 surface의 소비자 (UI 기능이면 사람, API라면 호출자)
- **구현 세부사항 금지** — 내부 타입, 상태 레이아웃, 모듈 경계 제외
- Validation/Testing 섹션 없음 — TECH.md의 역할

**필수 섹션**:

```markdown
## Summary
1-3문장

## Behavior
번호가 매겨진 테스트 가능 불변식:
1. 기본 동작 + 해피패스
2. 모든 사용자 가시 상태 + 전환
3. 모든 사용자 입력 + 응답
4. 빈 상태, 에러 상태, 로딩 상태, 취소
5. 권한 거부, 오프라인, 타임아웃, 경쟁 조건
6. 키보드/접근성/포커스
7. 반드시 유지해야 할 불변식 (회귀 금지)
```

**선택 섹션** (내용이 있을 때만):
- `## Problem` — 동기가 자명하지 않을 때만
- `## Goals / Non-goals` — 범위 논쟁이 있을 때
- `## Figma` — UI 기능 시 Figma 링크 또는 "none provided" 명시
- `## Open questions` — 인라인 `**Open question:**` 선호

**길이 기준**:
- 사소한 수정: 스펙 불필요
- 소규모 기능: ~30-60줄
- 중간 기능: ~80-150줄
- 대규모 기능: Behavior에 비례해 늘어나도 됨

---

### 2.3 `write-tech-spec` — TECH.md 작성

**전제조건**: PRODUCT.md가 먼저 있어야 함

**코드 조사 의무**: 초안 작성 전에 실제 코드, 타입, 데이터 흐름, 소유권 경계를 직접 확인. 추측 금지.

**필수 섹션**:

```markdown
## Context
- 현재 시스템 작동 방식
- 관련 파일 + 라인 레퍼런스
  예: `app/src/workspace/mod.rs:42` — 진입점
  예: `app/src/workspace/workspace.rs (120-220)` — 변경될 상태 처리
- PRODUCT.md 동작 재기술 금지 (참조만)

## Proposed Changes
- 변경될 모듈 목록
- 새 타입/API/상태
- 데이터 흐름 + 소유권 경계
- 트레이드오프 (대안이 있을 때)

## Testing and Validation
- PRODUCT.md의 Behavior 번호를 직접 참조
  예: "Invariant 3 — 단위 테스트: ..."
- 단위 테스트, 통합 테스트, 수동 검증 단계
- UI 변경 시 스크린샷/영상
```

**선택 섹션** (가치 있을 때만):
- `## End-to-end flow` — 계층 간 경로가 설명을 도울 때
- `## Diagram` — Mermaid 다이어그램 (1-2개 집중)
- `## Risks and mitigations` — 실제 실패 모드, 마이그레이션 우려
- `## Parallelization` — 에이전트 간 병렬화 가능할 때
- `## Follow-ups` — 미룬 정리 작업

**길이 기준**:
- 단일 파일 변경: 스펙 생략 또는 ~40줄
- 멀티 모듈 변경: ~80-150줄
- 대규모 아키텍처 변경: 각 섹션이 정당화되면 길어도 됨

---

### 2.4 `implement-specs` — 승인된 스펙 구현

**전제조건**:
- PRODUCT.md 존재 및 승인
- TECH.md 존재 (필요한 경우) 및 승인

**워크플로우**:
1. 스펙을 먼저 완전히 이해
2. 대규모 기능에는 선택적으로 `PROJECT_LOG.md` (체크포인트) 또는 `DECISIONS.md` (결정 사항) 제공 제안
3. 스펙에 맞춰 구현 (PRODUCT.md = 행동 진실, TECH.md = 아키텍처 진실)
4. **구현이 스펙에서 이탈하면 스펙 먼저 업데이트**
5. 코드 + 스펙 변경을 같은 PR에 포함
6. 완료 전 스펙 대비 검증

**핵심 원칙**: PR은 초안이 아닌 **실제 출하될 기능**을 설명해야 함.

---

### 2.5 `triage-issue-local` — 저장소별 이슈 트리아지 커스터마이즈

`triage-issue` 코어 스킬을 특화하는 예시. `specializes: triage-issue` 프론트매터로 선언.

커스터마이즈 가능 영역:
- 헤우리스틱 (공개 이슈 = 비공개 정보 요청 금지)
- 후속 질문 한도 (최대 2개)
- 레이블 분류 체계 (`.github/issue-triage/config.json` 참조)
- 정보 수집 전 확인 사항
- 반복 후속 패턴
- 오너 추론 힌트

---

### 2.6 `rust-unit-tests` — Rust 단위 테스트 패턴

**테스트 파일 위치**:
```
소스: app/src/feature/mod.rs
테스트: app/src/feature/mod_test.rs
         또는 app/src/feature/feature_tests.rs
```

**테스트 포함 방법** (소스 파일 끝에):
```rust
#[cfg(test)]
#[path = "mod_test.rs"]
mod tests;
```

**WarpUI 테스트 하네스**:
```rust
App::test((), |mut app| async move {
    initialize_app_for_terminal_view(&mut app);
    let term = add_window_with_terminal(&mut app, None);
    term.update(&mut app, |view, _ctx| { /* 상태 변경 */ });
    term.read(&app, |view, _ctx| { assert!(...) });
})
```

**주의사항**:
- `model.lock()` 중첩 금지 — 데드락
- `initialize_settings_for_tests` 직접 호출 금지 (이미 `initialize_app_for_terminal_view`에 포함)
- 전역 상태 건드리는 테스트: `serial_test::serial` 사용

---

## 3. 스킬 작성 Best Practices

Source: `.agents/skills/update-skill/references/best-practices.md`

### 3.1 설명(description) 작성 원칙

```
✓ 무엇을 하는지 + 언제 쓰는지를 구체적으로
✓ 3인칭으로 작성 ("Adds feature flags...")
✓ 트리거 용어 포함 (파일명, 명령어, 개념)
✗ 모호한 표현 ("Helps with features")
✗ 1/2인칭 ("I can help you...")
```

### 3.2 간결성 원칙

에이전트는 이미 전문 지식을 가지고 있다. 에이전트가 모르는 정보만 추가.

```
✗ Anti-pattern: PDF는 포터블 도큐먼트 포맷으로... (에이전트가 이미 앎)
✓ Good: pdfplumber를 텍스트 추출에 사용 + 코드 예시
```

### 3.3 워크플로우 vs 단순 지침

순서가 중요한 다단계 프로세스: 번호 단계 + 체크리스트
단순 작업: 제목 + 지침 (섹션 구조 불필요)

### 3.4 흔한 안티패턴

| 안티패턴 | 해결 |
|---------|------|
| Windows 스타일 경로 | 항상 `/` 사용 |
| 여러 옵션 나열 | 하나 추천 + 예외 케이스만 |
| 날짜/버전별 안내 | "현재 방법" / "구 패턴" 구분 |
| 용어 불일치 | 하나의 용어로 통일 |
| 자명한 것 설명 | 에이전트는 이미 앎 |
| 단순 스킬 과잉 구조화 | 필요한 섹션만 |

### 3.5 스킬 반복 개선

```
관찰 → 갭 식별 → 특정 섹션 수정 → 유사 작업 테스트
```

사전에 내용 추가 금지 — 실제 사용에서 필요성이 증명된 것만.

---

## 4. Jarvis 적용 시 제안

### 4.1 스킬 시스템 구조

Jarvis에 `.agents/skills/` 패턴을 도입한다면:

```
~/.jarvis/skills/           # 또는 프로젝트 내 .jarvis/skills/
├── <skill-name>/
│   └── SKILL.md
```

기존 `~/.jarvis/tools/`의 YAML 선언과 달리, 스킬은 **프로세스 가이드** — 에이전트가 어떻게 작업할지를 기술.

### 4.2 스펙 디렉토리

```
jarvis-projects/
└── specs/
    ├── feature-slug/
    │   ├── PRODUCT.md
    │   └── TECH.md
    └── ...
```

Behavior invariant를 번호로 작성 → FauxProvider 테스트에서 invariant 번호 참조.

### 4.3 가장 가치 있는 차용 아이디어

1. **Behavior invariant 번호 체계**: 기능 설명을 numbered list로 → 테스트와 1:1 매핑
2. **TECH.md의 "Testing and Validation" 섹션**: invariant 번호 직접 참조 → 누락 없는 검증
3. **스킬 설명의 트리거 용어**: Jarvis의 스킬 라우팅에 활용 가능
4. **references/ 분리**: 스킬이 길어지면 필요 시에만 로드되는 참조 파일로 분리
5. **PROJECT_LOG.md 패턴**: 장기 작업에서 에이전트 체크포인트 추적
