# Proactive Jarvis — Inner Thought 기반 설계

> 상태: **구현 완료** — 본 문서는 설계 의도/로드맵의 기준점이며, Tier 0~3 전부 반영되었다.
> 실제 구현 현황·모듈 지도·설정은 [proactive-implementation.md](proactive-implementation.md) 참조.
> 관련: [jarvis-architecture.md](jarvis-architecture.md) · [pi-reference](ref_analysis/pi-reference.md)

## 0. 한 줄 요약

Jarvis를 "요청에만 응답하는 reactive agent"에서 **"사람처럼 내적으로 사고(inner thought)하고, 스스로 판단해 먼저 행동하는 proactive agent"** 로 확장한다.
핵심은 두 가지: ① 요청 시점에 도는 **메타인지 층(Inner Thought Engine)**, ② 요청이 없어도 도는 **성찰 루프(Proactivity Daemon)** + **언제 말할지 판단하는 결정 정책**.

## 1. 설계 원칙

1. **레이어 규칙 준수** (Hard Rule #1) — LLM을 호출하는 사고 엔진은 `agent_layer/`, 오케스트레이션은 `core/`. `model_layer`는 위를 모른다.
2. **inner thought는 편집 가능한 프롬프트 1개 + 모듈 1개로 격리** — 사용자가 직접 사고 방식을 조율한다.
3. **절제 우선** — proactive agent의 실패는 능력이 아니라 *타이밍/과잉*에서 온다. 기본은 침묵 쪽으로 편향.
4. **저위험 자율 / 고위험 승인** — 읽기·검색·메모·초안은 자율, 외부/파괴적 행동은 기존 HITL 승인 파이프라인을 그대로 탄다.
5. **관찰 가능성** — 모든 inner thought와 proactive 결정은 로그/이벤트로 노출되어 사용자가 들여다보고 디버깅할 수 있다.

## 2. 현재 자산 (substrate) — 이미 있는 것

proactive agent 하부구조의 ~70%는 이미 존재한다. 신규 작업은 "두뇌"와 "입(먼저 말하기)"에 집중된다.

| 자산 | 위치 | proactive에서의 역할 |
|------|------|---------------------|
| 자율 실행 루프 | `core/scheduler/service.py` | 요청 없이 도는 백그라운드 실행의 토대 (cron) |
| 메모리 STM/LTM/Episodic | `agent_layer/memory/` | 사고가 회상할 컨텍스트 |
| 벡터 검색 어댑터 | `agent_layer/memory/adapters/vector.py` | 의미 기반 관련 기억 회상 |
| 이벤트 스트림 | `agent_layer/types.py` (`AgentEvent`) | inner thought / proactive 메시지를 UI로 전달 |
| WebSocket push | `ui/web/server.py` | 서버→클라이언트 비요청 푸시 (이미 가능) |
| 플러그인 훅 | `core/plugins/protocol.py` | `before_agent_start`, `transform_context` 등 삽입점 |
| 보안 파이프라인 / Sandbox | `core/policy/` | 저위험/고위험 행동 게이팅(HITL 승인) |
| MCP 클라이언트 | `core/tools/mcp_loader.py` | 외부 세계 감지 (캘린더·메일 등) |

**빠진 것 5가지:** ① Inner Thought Engine ② 결정 정책(act/ask/silent) ③ Push 아웃바운드 채널 ④ 백그라운드 성찰 루프 ⑤ open-loop/목표 추적.

## 3. 핵심 개념: Inner Thought

요청이 들어온 시점(또는 백그라운드 성찰 시점)에 **메인 응답과 분리된 별도 LLM 호출**로 구조화된 내적 사고 `ThoughtFrame`을 만든다. 이 프레임이 ① 메인 턴의 컨텍스트를 증강하고, ② "지금 먼저 행동/발화할지" 판단을 산출한다.

### 3.1 `ThoughtFrame` (제안 스키마)

```python
# agent_layer/thought/types.py
class ProactiveAction(BaseModel):
    kind: Literal["suggest", "tool", "remember", "schedule"]
    description: str            # 사람이 읽을 수 있는 행동 설명
    tool_name: str | None = None
    args: dict[str, Any] = {}
    risk: Literal["low", "high"] = "low"   # 저위험=자율, 고위험=승인

class ThoughtFrame(BaseModel):
    observation: str            # 무엇이 들어왔는가 (사실)
    interpretation: str         # 의도 / 감정 / 숨은 니즈 해석
    recalled: list[str] = []    # 회상한 관련 기억(LTM) 요약
    options: list[str] = []     # 가능한 대응 후보
    proactive_actions: list[ProactiveAction] = []
    decision: Literal["act", "ask", "silent"]   # 먼저 행동할지/물어볼지/가만히 있을지
    confidence: float           # 0.0–1.0
    rationale: str              # 결정 근거 (관찰 가능성)
```

> 사용자는 주로 **프롬프트 템플릿**(§7)을 편집해 이 프레임이 채워지는 방식을 조율한다. 스키마 자체는 안정적으로 유지.

## 4. 아키텍처 — 두 협력 서브시스템

```
                ┌─────────────────────────────────────────────┐
   사용자 요청 ──→│ AgentSession.prompt()                       │
                │   security → skill.expand                    │
                │   ┌──────────────────────────────┐           │
                │   │ (1) InnerThoughtEngine.think() │←─ 메모리 회상
                │   │     → ThoughtFrame             │           │
                │   └──────────────────────────────┘           │
                │   ThoughtFrame를 메인 턴 컨텍스트로 주입       │
                │   harness.run() → run_agent_loop             │
                └─────────────────────────────────────────────┘
                                   │ InnerThoughtEvent / proactive 결정
                                   ▼
   (요청 없음)   ┌─────────────────────────────────────────────┐
   주기/이벤트 ─→│ (2) ProactivityDaemon (scheduler 형제)        │
                │   open-loop·최근 메모리 성찰 → ThoughtFrame   │
                │   결정 정책 게이팅 → PushChannel              │
                └─────────────────────────────────────────────┘
                                   │ proactive_message
                                   ▼
                            사용자 (TUI / Web / OS 알림)
```

### (1) Inner Thought Engine — `agent_layer/thought/`
- 요청 시점 메타인지. 저렴/빠른 모델(설정으로 메인과 분리 가능)로 `ThoughtFrame` 생성.
- 결과를 메인 턴에 주입(system_prompt 증강 또는 합성 컨텍스트 메시지).
- `ThoughtFrame`을 **사고 로그**(새 메모리 타입)로 영속화.

### (2) Proactivity Daemon — `core/proactive/`
- `SchedulerService`와 형제. 주기적으로(또는 트리거 이벤트로) open-loop·최근 메모리를 inner thought로 성찰.
- 산출된 `proactive_actions`를 결정 정책(§6)으로 게이팅 → 통과분만 Push 채널로 전달.

## 5. 요청 시점 흐름 (구체적 삽입 지점)

`core/session.py:69` `AgentSession.prompt()` 의 현재 순서:

```
SecurityPipeline.run → SkillRegistry.expand → emit_before_agent_start → harness.run
```

**삽입:** `expand` 직후, `harness.run` 직전.

```python
# core/session.py (의사코드)
expanded = self._skill_registry.expand(validated.sanitized)

frame = None
if self._thought_engine is not None:
    frame = await self._thought_engine.think(
        user_input=expanded,
        history=await self._session_repo.get_messages(self._session_id),
        recall=self._memory_recall,   # LTM/벡터 회상 콜백
        session_id=self._session_id,
    )
    await self._emit_inner_thought(frame)        # InnerThoughtEvent (§8)
    await self._thought_log.store(frame)         # 사고 로그 영속화

await self._plugins.emit_before_agent_start(expanded, {...})
result = await self._harness.run(
    user_input=expanded,
    tool_executor=...,
    extra_context={..., "inner_thought": frame.model_dump() if frame else None},
)
```

- `harness.run`은 `extra_context`를 `AgentContext.metadata`로 전달(`harness.py:75`). 메인 루프 system_prompt 증강에 `frame.interpretation` 등을 사용.
- **저위험 자율 행동**: `frame.decision == "act"` 이고 `proactive_actions`가 전부 `risk == "low"`면, 메인 응답 전에 그 행동(예: 관련 파일 미리 읽기/검색)을 자율 실행해 컨텍스트에 얹는다. `risk == "high"`는 `ask`로 강등.

## 6. 결정 정책 — 저위험 자율 실행 (확정된 boldness)

inner thought의 `decision`과 각 `ProactiveAction.risk`를 조합해 게이팅한다.

| 행동 위험도 | 예시 | 처리 |
|-------------|------|------|
| **low (자율)** | `read_file`, `glob`, `grep`, `list_dir`, `web_search`, `web_fetch`, 기억 회상/저장(`/remember`), 제안 초안 작성, 사고 로그 | **승인 없이 자율 실행** |
| **high (승인)** | `bash`(쓰기/실행), `write_file`, `edit_file`, 외부 상태 변경, 외부로 메시지 발송, mutate성 MCP 툴 | **기존 Sandbox HITL 승인** 경유 |

- 위험도 분류는 신규로 따로 만들지 않고 **기존 `DefaultSandbox.require_approval_for`** 와 툴별 정책을 재사용한다. inner thought가 `risk`를 추정하되, 최종 강제는 기존 보안 파이프라인이 한다(이중 안전장치).
- **발화 절제 (anti-nagging):** `decision`이 `act`/`ask`라도, proactive 발화는 `confidence ≥ threshold`(설정, 기본 보수적) 일 때만 사용자에게 노출. 미달이면 `silent`로 강등하고 사고 로그에만 남긴다.
- **속도 제한:** proactive 발화에 쿨다운/빈도 상한(설정) — `core/session.py`의 기존 rate-limit 패턴 재사용.

## 7. 사용자 편집 지점 — Inner Thought 프롬프트 템플릿

사용자가 "직접 수정"할 대상. 코드가 아니라 **프롬프트 파일**로 격리한다.

- 경로: `~/.jarvis/inner_thought.md` (없으면 패키지 기본 템플릿 사용)
- 플레이스홀더: `{{user_input}}`, `{{history}}`, `{{recalled_memories}}`, `{{now}}`, `{{open_loops}}`
- 출력 계약: 모델이 `ThoughtFrame` JSON을 반환하도록 지시(구조화 출력). 파싱 실패 시 graceful fallback(사고 생략, 일반 응답).
- 설정(`config.py`의 새 `ThoughtConfig`):
  ```bash
  JARVIS_THOUGHT__ENABLED=true
  JARVIS_THOUGHT__MODEL=             # 비우면 메인 모델, 지정 시 별도(저렴) 모델
  JARVIS_THOUGHT__PROMPT_PATH=~/.jarvis/inner_thought.md
  JARVIS_THOUGHT__CONFIDENCE_THRESHOLD=0.6
  JARVIS_THOUGHT__PROACTIVE_COOLDOWN_SEC=300
  ```

## 8. Push(아웃바운드) 채널 — 먼저 말하기

지금은 요청에만 응답한다. 비요청 발화 경로를 추가한다.

- **이벤트:** `agent_layer/types.py`에 `InnerThoughtEvent`(사고 시각화) + `ProactiveMessageEvent`(먼저 거는 말) 추가 → `AgentEvent` 유니온에 합류.
- **UIAdapter 확장:** `ui/protocol.py`에 `on_proactive_message(text, meta)` 추가.
  - **Web:** WS 메시지 타입 `proactive_message` 추가(서버→클라이언트). `connected` 외에 서버가 자발적으로 push (이미 구조적으로 가능). HUD에 별도 "JARVIS가 먼저 건넨 말" 스타일.
  - **TUI:** 채팅에 구분된 스타일로 표시(예: `💭`/`🔔`). 사고 스트림은 status/별도 패널.
  - **OS 알림(선택):** 백그라운드 daemon 발화 시 데스크톱 알림(best-effort, 플랫폼별).

## 9. 백그라운드 성찰 — Proactivity Daemon

- 위치: `core/proactive/daemon.py` (스케줄러 형제, 동일한 `asyncio` 루프 패턴 `scheduler/service.py:61`).
- 주기 틱마다: 최근 메모리 + open-loop를 모아 `InnerThoughtEngine.think()` 호출(요청 없는 성찰 모드) → `proactive_actions` 산출 → 결정 정책(§6) → 통과분 Push.
- **트리거 종류(점진 도입):** 시간(cron 재사용) → idle 감지 → 외부 이벤트(MCP 캘린더/메일) → 메모리 이벤트.
- **무엇에 대해(open-loop):** §10.

## 10. Open-loop / 목표 추적

proactive의 "대상". 사용자가 흘린 약속·미완 작업을 추적한다.

- 저장소: `agent_layer/memory/` 의 LTM에 `source="open_loop"` 타입으로, 또는 전용 경량 store.
- 스키마: `{id, description, created_at, due?, status: open|done|dismissed, origin_session}`.
- 갱신: inner thought가 대화에서 open-loop를 추출(`proactive_actions`의 `remember`/`schedule`) → daemon이 만기/조건 충족 시 상기.
- 스케줄러의 `run_until` 만기 패턴(`scheduler/task.py`)을 참고.

## 11. 파일 배치 / 레이어 매핑

```
agent_layer/
  thought/
    __init__.py
    types.py          # ThoughtFrame, ProactiveAction
    engine.py         # InnerThoughtEngine.think() — 별도 LLM 호출, 프롬프트 렌더
    prompt.py         # 템플릿 로딩(~/.jarvis/inner_thought.md) + 기본 템플릿
    log.py            # 사고 로그 (메모리 백엔드 재사용 or 전용)
  memory/
    backends/...      # open_loop source 추가 (기존 LTM 재사용)
core/
  proactive/
    __init__.py
    daemon.py         # ProactivityDaemon — scheduler 형제
    policy.py         # 결정 게이팅(confidence threshold, risk, cooldown)
  session.py          # think() 삽입 + proactive 자율 실행 분기 (§5)
ui/
  protocol.py         # on_proactive_message 추가
  tui/app.py, web/... # InnerThought/ProactiveMessage 이벤트 렌더
config.py             # ThoughtConfig, ProactiveConfig
```

레이어 방향 점검: `thought/engine.py`는 `model_layer`만 의존(OK). 오케스트레이션·정책은 `core`(OK). UI는 이벤트만 소비(OK).

## 12. 단계별 구현 로드맵

| Tier | 항목 | 산출물 | 의존 |
|------|------|--------|------|
| **0** | Inner Thought Engine | `agent_layer/thought/*`, `ThoughtConfig`, `session.py` 삽입, `InnerThoughtEvent` + UI 시각화, 편집 가능 프롬프트, 사고 로그 | — |
| **1** | 결정 정책 + Push | `core/proactive/policy.py`, `ProactiveMessageEvent`, `UIAdapter.on_proactive_message`, TUI/Web 렌더 | Tier 0 |
| **1** | Proactivity Daemon | `core/proactive/daemon.py` (cron 트리거부터) | Tier 0,1 |
| **2** | Open-loop 추적 | LTM `open_loop` source + 추출/상기 | Tier 1 |
| **2** | 외부 트리거 | MCP 캘린더/메일 + idle 감지 | Tier 1 |
| **2** | 피드백 학습 | 수락/무시 기록 → threshold 조정 | Tier 1 |
| **3** | Working-memory/유저모델, self-reflection 저널 | LTM 증류 + 주기 저널 | Tier 2 |

권장 구현 순서: **Tier 0 → (정책+Push) → Daemon → open-loop**. Tier 0가 모든 후속의 입력을 공급하므로 단독으로도 가치(메인 응답 품질↑) 발생.

## 13. 테스트 전략 (실 API 없이)

- `InnerThoughtEngine.think()`: faux provider로 `ThoughtFrame` JSON 반환 → 파싱/검증, 파싱 실패 fallback.
- 결정 정책: confidence threshold / risk 분류 / cooldown 경계값 단위 테스트(순수 함수).
- Daemon: scheduler 테스트 패턴(`test_scheduler.py`) 재사용 — 트리거 발화 → push 호출 검증(fake channel).
- Push 채널: fake UIAdapter로 `on_proactive_message` 호출 검증.
- 저위험/고위험 게이팅: 저위험은 자율 실행, 고위험은 승인 콜백 호출됨을 mock으로 검증.

## 14. 리스크 / 미해결 질문

1. **과잉 발화** — 가장 큰 위험. 보수적 threshold + cooldown + 피드백 학습(Tier 2)으로 완화. 초기엔 발화보다 사고 로그 위주로 시작 권장.
2. **지연/비용** — 요청마다 사고 LLM 호출은 레이턴시·비용↑. 별도 저렴 모델 + 조건부 실행(예: 짧은 인사엔 사고 생략)로 완화.
3. **현재 세션 컨텍스트** — `/compact`/`/export`처럼 일부 경로가 `default` 세션 고정. proactive가 멀티 세션을 다루려면 dispatcher/엔진에 current-session getter 주입 필요(별도 작업).
4. **구조화 출력 신뢰성** — 로컬/소형 모델은 JSON 계약을 어길 수 있음. 엄격 파싱 + fallback 필수.
5. **프라이버시** — 사고 로그/유저 모델이 민감정보 축적. 저장 위치·보존정책 명시 필요.

---

## 부록 A. Inner Thought 기본 프롬프트(초안 골격)

```
너는 Jarvis의 "내적 사고" 모듈이다. 사용자에게 직접 답하지 않는다.
아래 입력을 보고 ThoughtFrame JSON 하나만 출력하라.

[지금] {{now}}
[열린 약속] {{open_loops}}
[회상된 기억] {{recalled_memories}}
[최근 대화] {{history}}
[사용자 입력] {{user_input}}

다음을 채워라:
- observation: 표면적 사실
- interpretation: 진짜 의도, 감정, 말하지 않은 니즈
- recalled: 활용할 기억 요약
- options: 가능한 대응들
- proactive_actions: 지금 먼저 해두면 좋은 행동(각각 risk: low|high)
- decision: act | ask | silent  (확신 없으면 silent로 기울여라)
- confidence: 0..1
- rationale: 위 결정의 이유

원칙: 도움이 안 되면 침묵하라. 저위험 행동만 자율 제안하라.
```

> 이 파일(`~/.jarvis/inner_thought.md`)이 사용자가 직접 조율하는 지점이다.
