# Proactive Jarvis — 구현 레퍼런스 (As-Built)

> 상태: **구현 완료(Tier 0~3 + Phase 3 외부 트리거)**. 본 문서는 실제 코드 기준의 구현 현황·모듈 지도·설정 레퍼런스다.
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
| **P3** | 외부 트리거 — MCP 소스 폴링 → dedup → inbox → 사고 주입 | ✅ | — |

미연결 항목 없음. 마지막 플러그 지점이던 `ExternalTrigger.fire()`는 [ExternalEventPoller](../src/jarvis/core/external/poller.py)가 채웠다 — 설계 근거는 [proactive-external-trigger-design.md](proactive-external-trigger-design.md).

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
  external/                # Phase 3 — 외부 세계 감지 (소스 YAML 없으면 전 구간 no-op)
    types.py               #   ExternalEvent (원문 패스스루, as_line으로 사고에 주입)
    protocol.py            #   ExternalSource Protocol (MCP 아닌 소스도 같은 자리)
    loader.py              #   ~/.jarvis/external_sources/*.yaml → ExternalSourceSpec
    mcp_source.py          #   McpToolSource — 서버 지정 MCP 툴 1회 호출 (ToolRegistry 우회)
    dedup.py               #   derive_events(키 추론) + SeenStore(InMemory/Jsonl, TTL·상한)
    inbox.py               #   ExternalEventInbox — 앱 레벨 단일 큐, drain-once
    poller.py              #   ExternalEventPoller — 소스별 주기 폴링 → dedup → inbox + fire()
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

## 4-1. 외부 이벤트 흐름 (Phase 3)

```
ExternalEventPoller (백그라운드 루프, 소스별 interval)
  → McpToolSource.poll()            # MCP 툴 호출 → 원문 텍스트 (서버별 timeout)
  → derive_events()                 # 아이템 분해 + id/해시 키 추론
  → SeenStore.filter_new()          # 이미 본 키 제거 (JSONL replay, TTL·max_keys)
  → ExternalEventInbox.put()        # payload 적재 (트리거와 분리)
  → ExternalTrigger.fire()          # daemon 깨우기

ProactivityDaemon.tick() → session.reflect()
  → inbox.drain()                   # 최근 활동 세션이 전부 소비 → 이벤트당 발화 1회
  → ThoughtRequest(external_events=[...], mode="reflection")
  → 기존 policy 게이팅 (threshold·cooldown·피드백 학습)
```

소스 선언은 `~/.jarvis/external_sources/*.yaml` — 예제: [examples/external_sources/calendar_mail.yaml](examples/external_sources/calendar_mail.yaml).
`server`는 `mcp_servers` 이름으로 해석하며 ToolRegistry를 경유하지 않는다(서버 간 툴 이름 충돌 회피).

외부 트리거는 `daemon_trigger`와 **직교**한다 — 소스가 있으면 `AnyTrigger`로 항상 합성되어
`daemon_trigger=interval`이어도 외부 이벤트로 깨어난다. 파일이 없으면 폴러 자체가 기동하지 않는다.

**프라이버시:** 원문은 `detail_max_chars`로 절단되고, 기본값(`store_detail_in_log=false`)에서는
사고 프롬프트에 **제목만** 실린다 — 메일 본문이 사고 로그·LTM에 축적되지 않는다(제목을 추론하지
못한 비정형 소스만 원문으로 폴백). 자율 실행 화이트리스트는 그대로 읽기 전용이라, 외부 이벤트가
메일 발송·일정 생성 같은 쓰기를 유발할 수 없다.

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
| `JARVIS_EXTERNAL__ENABLED` | `true` | 외부 트리거 마스터 스위치 (소스 없으면 자동 no-op) |
| `JARVIS_EXTERNAL__SOURCES_DIR` | `~/.jarvis/external_sources` | 소스 YAML 디렉토리 |
| `JARVIS_EXTERNAL__SEEN_BACKEND` / `__SEEN_PATH` | `jsonl` / `~/.jarvis/external_seen.jsonl` | dedup 저장소 |
| `JARVIS_EXTERNAL__SEEN_TTL_SEC` / `__SEEN_MAX_KEYS` | `604800` / `10000` | dedup 키 보관·상한 |
| `JARVIS_EXTERNAL__MAX_EVENTS_PER_TICK` / `__INBOX_MAX_EVENTS` | `20` / `200` | 성찰 1회 상한 / inbox 상한 |
| `JARVIS_EXTERNAL__DETAIL_MAX_CHARS` | `500` | 원문 절단 길이 |
| `JARVIS_EXTERNAL__STORE_DETAIL_IN_LOG` | `false` | 원문을 사고 프롬프트(→로그)에 실을지 |

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

`tests/unit/test_thought*.py`, `test_proactive*.py`, `test_triggers.py`, `test_feedback.py`, `test_openloop*.py`, `test_usermodel.py`, `test_journal.py`, `test_bridge_proactive.py`, `test_external.py`, `test_external_wiring.py` — 전부 faux provider로 실 API 없이 검증(실 MCP 서버도 불필요 — `call_mcp_tool`을 fake로 주입). 정책 게이팅·Dual-Channel·daemon·이중 게이트·증류 fallback·재로드 복원, 그리고 키 추론 4경로·dedup TTL/상한·drain-once·소스별 주기·예외 격리·템플릿 append 폴백까지 커버.
