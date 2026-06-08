# Proactive Jarvis — 구현 레퍼런스 (As-Built)

> 상태: **구현 완료(Tier 0~3)**. 본 문서는 실제 코드 기준의 구현 현황·모듈 지도·설정 레퍼런스다.
> 설계 의도: [proactive-inner-thought-design.md](proactive-inner-thought-design.md) · 전체 구조: [jarvis-architecture.md](jarvis-architecture.md)

## 0. 한 줄 요약

Jarvis는 요청에만 답하지 않고, 매 요청마다 **별도로 사고(inner thought)** 하고, 오래 걸릴 작업엔 **먼저 운을 떼고 백그라운드로 처리(Dual-Channel)** 하며, 요청이 없어도 **스스로 성찰해 먼저 말 거는(Proactivity Daemon)** proactive agent다. 사용자의 약속을 추적(open-loop)하고, 피드백으로 발화 절제를 학습하며, 사용자 모델·자기 성찰 저널로 장기 인지를 쌓는다.

모든 핵심 로직은 **독립 class(Protocol 뒤 격리)** 로 구현되어 통째 교체·커스텀 가능하다.

## 1. 구현 현황 (Tier 0~3)

| Tier | 항목 | 상태 | PR |
|------|------|------|----|
| **0** | Inner Thought Engine | ✅ | #29 |
| 0+ | A1 모델 분리 / A2 로그 싱크 / A3 composer | ✅ | #29 |
| **1** | B1 결정 정책 + 독립 ProactivityCore | ✅ | #30 |
| 1 | B2 Push 채널 (filler/proactive 이벤트, voice TTS) | ✅ | #30 |
| 1 | B3 Proactivity Daemon (Dual-Channel + 자율 push) | ✅ | #30 |
| 1+ | E1 멀티세션 daemon / E3 reflection 전용 템플릿 | ✅ | #31 |
| **2** | C1 Open-loop 추적 + E2 저위험 자율 실행 | ✅ | #32 |
| 2 | open-loop 영속화 (jsonl / postgres) | ✅ | #32 |
| 2 | C2 성찰 트리거(interval/idle/external) | ✅ | #33 |
| 2 | C3 피드백 학습 (수락/무시 → 임계치) | ✅ | #33 |
| **3** | D1 User Model (기억 증류 → 사고 주입) | ✅ | — |
| 3 | D2 Self-reflection 저널 | ✅ | — |

**미연결(플러그 지점만 마련):** MCP 캘린더·메일 실폴링(`ExternalTrigger.fire()`에 연결할 어댑터) — 설정된 MCP 서버·툴 스키마에 의존해 server-specific.

## 2. 모듈 지도

```
agent_layer/
  thought/                 # Tier 0 — Inner Thought 서브시스템
    types.py               #   ThoughtFrame / ProactiveAction / ThoughtRequest
    protocol.py            #   ThoughtEngine Protocol (교체 가능)
    engine.py              #   InnerThoughtEngine — 별도 LLM 호출, seam 메서드 오버라이드
    prompt.py              #   요청/성찰 템플릿(편집 가능) + 로딩
    composer.py            #   ThoughtComposer — 사고→프롬프트 조립 전략 (A3)
    log.py                 #   ThoughtSink — LTM/STM 사고 로그 싱크 (A2)
  openloop/                # Tier 2 — 약속/미완 작업 추적 (C1)
    types.py / store.py    #   OpenLoop / OpenLoopStore(InMemory)
    jsonl_store.py         #   JSONL 영속(append-log replay)
    postgres_store.py      #   Postgres 영속(asyncpg)
  usermodel/               # Tier 3 D1 — 사용자 모델
    types.py / store.py / builder.py
  journal/                 # Tier 3 D2 — 자기 성찰 저널
    journaler.py           #   사고 로그(source=thought) → 저널(source=journal)
core/
  proactive/               # Tier 1~2 — proactive 코어 (독립)
    types.py               #   ProactiveMessage / ResponsePlan / ProactiveDecision
    policy.py              #   ProactivityPolicy + Default (게이팅·쿨다운·위험도·동적임계)
    core.py                #   ProactivityCore + Default (Dual-Channel 오케스트레이터)
    daemon.py              #   ProactivityDaemon (성찰 루프, 멀티세션)
    triggers.py            #   ReflectionTrigger(Interval/Idle/External/Any) (C2)
    feedback.py            #   FeedbackLearner — 수락/무시 → 임계치 (C3)
  session.py               #   think() 삽입 + Dual-Channel + reflect() + 자율실행 + 주입
core/slash/                # /openloop, /usermodel, /journal 커맨드
```

레이어 규칙(Hard Rule #1) 준수: 사고 엔진·증류기는 `model_layer`만 의존, 오케스트레이션·정책은 `core`, UI는 이벤트만 소비.

## 3. 요청 흐름 (Dual-Channel)

```
session.prompt(user_input)
  → security → skill.expand
  → InnerThoughtEngine.think()            # 별도 LLM 호출 → ThoughtFrame
       · open_loops + user_model 주입       # 회상 컨텍스트
       · InnerThoughtEvent emit (💭)        # 관찰
       · 감지한 open_loop 저장 / 사고 로그 저장
  → ProactivityCore.dispatch_request(frame, run_main)
       · needs_background=false → run_main() 동기(스트리밍)
       · needs_background=true  → filler 즉시 발화(voice TTS) + run_main 백그라운드
```

## 4. 자율 성찰 흐름 (Daemon)

```
ProactivityDaemon  ── trigger.wait() (interval | idle | external) ──→ tick()
  → 활성 세션마다 session.reflect()
       → think(mode="reflection")          # 성찰 전용 템플릿(절제 강화)
       → ProactivityCore.reflect(frame, execute=_execute_autonomous)
            · policy.decide_proactive       # decision×confidence(동적)×cooldown 게이팅
            · 통과 시: 저위험 자율 행동 실행(이중 게이트) → 요약을 메시지에 덧붙임
            · ProactiveMessageEvent push (🔔, voice TTS)
```

**E2 이중 안전 게이트:** 자율 실행은 `{read_file, glob, grep, list_dir, web_search, web_fetch}` 화이트리스트 ∩ sandbox 승인 불필요 — 둘 다 통과한 읽기 전용 툴만. 고위험·외부 변경·승인 대상은 절대 자율 실행하지 않는다(요청 없는 시점엔 승인 주체 부재).

## 5. 피드백 학습 (C3)

proactive 발화에 사용자가 👍/👎(Web 버튼 · TUI `Ctrl+Y`/`Ctrl+G` · voice 키워드) → `session.record_feedback()` → `FeedbackLearner`가 임계치 조정(무시↑·수락↓, 경계 [0.3, 0.95]). 정책은 학습기의 동적 임계치를 사용한다.

## 6. 설정 레퍼런스

| 환경변수 | 기본 | 설명 |
|----------|------|------|
| `JARVIS_THOUGHT__ENABLED` | `true` | Inner Thought 마스터 스위치 |
| `JARVIS_THOUGHT__MODEL` / `__PROVIDER` / `__API_KEY` / `__BASE_URL` | (메인 상속) | 사고 모델 분리 (A1) |
| `JARVIS_THOUGHT__PROMPT_PATH` | `~/.jarvis/inner_thought.md` | 요청 사고 템플릿 |
| `JARVIS_THOUGHT__REFLECTION_PROMPT_PATH` | `~/.jarvis/inner_thought_reflection.md` | 성찰 템플릿 |
| `JARVIS_THOUGHT__LOG_SINKS` | `["ltm"]` | 사고 로그 싱크 (ltm/stm, A2) |
| `JARVIS_THOUGHT__COMPOSER` | `default` | 조립 전략 (default/interpretation_only, A3) |
| `JARVIS_PROACTIVE__ENABLED` | `true` | Dual-Channel 마스터 스위치 |
| `JARVIS_PROACTIVE__CONFIDENCE_THRESHOLD` | `0.6` | 발화 게이팅 임계치(학습기 base) |
| `JARVIS_PROACTIVE__COOLDOWN_SEC` | `300` | 세션별 발화 쿨다운 |
| `JARVIS_PROACTIVE__DAEMON_ENABLED` | `true` | 자율 성찰 루프 (기본 on, false로 끔) |
| `JARVIS_PROACTIVE__DAEMON_TRIGGER` | `interval` | interval / idle / both |
| `JARVIS_PROACTIVE__DAEMON_INTERVAL_SEC` / `__DAEMON_IDLE_SEC` | `900` / `180` | 트리거 주기 |
| `JARVIS_OPENLOOP__BACKEND` / `__PATH` | `jsonl` | open-loop 영속 (jsonl/in_memory/postgres) |
| `JARVIS_USER_MODEL__ENABLED` / `__BACKEND` / `__PATH` | `true` / `jsonl` | 사용자 모델 |

## 7. 슬래시 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/openloop` `[done\|dismiss <id>]` | 추적 중인 약속/미완 작업 |
| `/usermodel` `[build]` | 증류된 사용자 모델 표시/갱신 |
| `/journal` `[write]` | 자기 성찰 저널 표시/작성 |

## 8. WebSocket 이벤트 (proactive)

```json
// Server → Client
{"type": "inner_thought", "interpretation": "...", "decision": "act|ask|silent", "confidence": 0.0, "frame": {...}}
{"type": "proactive_message", "text": "...", "kind": "filler|proactive|answer", "speak": false, "message_id": "..."}
// Client → Server
{"type": "proactive_feedback", "id": "<message_id>", "accepted": true}
```

## 9. 안전성 / 기본 동작

- `THOUGHT`/`PROACTIVE` 비활성 시 모든 분기 완전 skip → 기존 reactive 동작과 동일(제로 오버헤드).
- 사고/증류/회상 실패는 예외 대신 graceful fallback → 메인 턴을 절대 막지 않음.
- daemon은 기본 ON(요청 없이 먼저 말 검) — `JARVIS_PROACTIVE__DAEMON_ENABLED=false`로 끈다. 발화는 confidence 임계치+쿨다운+피드백 학습으로 절제되고, 확신 없으면 silent로 기운다.
- 자율 실행은 읽기 전용 이중 게이트로 한정.

## 10. 테스트

`tests/unit/test_thought*.py`, `test_proactive*.py`, `test_triggers.py`, `test_feedback.py`, `test_openloop*.py`, `test_usermodel.py`, `test_journal.py`, `test_bridge_proactive.py` — 전부 faux provider로 실 API 없이 검증. 정책 게이팅·Dual-Channel·daemon·이중 게이트·증류 fallback·재로드 복원 등 커버.
