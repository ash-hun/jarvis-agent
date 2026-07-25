# Proactive Phase 3 — 외부 트리거(MCP) 설계

> 상태: **설계 확정 · 미구현**. Tier 2의 마지막 미연결 항목(`ExternalTrigger.fire()` 어댑터)을 채운다.
> 설계 의도: [proactive-inner-thought-design.md](proactive-inner-thought-design.md) · 구현 현황: [proactive-implementation.md](proactive-implementation.md)

## 0. 목표

캘린더·메일 등 **외부 세계의 변화**를 조용히 감지해서, daemon이 **무슨 일이 생겼는지 알고** 성찰하고, 말할 가치가 분명할 때만 먼저 말한다.

비목표(이번 범위 아님):
- 외부 시스템에 쓰기(메일 발송·일정 생성) — proactive 자율 실행은 [AUTONOMOUS_SAFE_TOOLS](../src/jarvis/core/session.py) 화이트리스트에 갇혀 있고 그대로 둔다.
- cron으로 "매일 9시에 캘린더 확인해줘" — 이미 [SchedulerService](../src/jarvis/core/scheduler/service.py)가 커버한다(에이전트 턴 전체를 돌리는 무거운 경로). 본 설계는 **턴 없이 사고에만 먹이는** 가벼운 경로다.

## 1. 현재 끊어진 사슬

| # | 공백 | 위치 |
|---|------|------|
| 1 | 폴러 부재 — `ExternalTrigger.fire()` 호출자 0건 | [startup.py:492](../src/jarvis/ui/tui/startup.py#L492) |
| 2 | **트리거에 payload 없음** — 맨 `asyncio.Event`. 깨워도 `reflect()`는 고정 `REFLECTION_SEED`를 쓰므로 사고 모델은 무슨 일이 생겼는지 모른다 | [triggers.py:93](../src/jarvis/core/proactive/triggers.py#L93), [session.py:185](../src/jarvis/core/session.py#L185) |
| 3 | dedup 상태 없음 — 폴링마다 같은 회의·메일을 새 이벤트로 재발화 | — |
| 4 | 멀티세션 팬아웃 — web daemon은 활성 세션 전체를 성찰시킨다 | [server.py:123](../src/jarvis/ui/web/server.py#L123) |
| 5 | MCP 툴 이름·인자·응답이 서버마다 다름 | [mcp_loader.py](../src/jarvis/core/tools/mcp_loader.py) |

②가 핵심이다. 폴러만 붙이면 "뭔가 생겼으니 성찰해봐"라는 **내용 없는 깨우기**가 된다.

## 2. 설계 결정 (확정)

| 결정 | 선택 | 근거 |
|------|------|------|
| 소스 정의 | **YAML 선언 + 원문 패스스루** | 레포에 벤더 파서 0줄. 어떤 MCP 서버든 동작하고, 해석은 inner thought LLM이 담당(기존 철학과 일치) |
| dedup 키 | **아이템별 키 자동추론 + 텍스트 해시 폴백** | 벤더 스키마 지식 없이 아이템 단위 정확도 확보. 파싱 실패에도 조용히 동작 |
| 세션 전달 | **inbox drain-once → 최근 활동 세션** | 이벤트당 발화 1회. 중복 발화를 원천 차단 |
| 발화 게이팅 | **기존 policy 그대로** (threshold·cooldown·피드백 학습) | 과잉 발화가 최대 리스크(설계문서 §14-1). 정책 경로를 하나로 유지 |

## 3. 모듈 구조

```
core/external/                 # 신규 (core 레이어 — MCP 설정·세션과 같은 층)
  types.py       ExternalEvent
  protocol.py    ExternalSource Protocol (poll)
  loader.py      YAML → ExternalSourceSpec 파싱
  mcp_source.py  McpToolSource — MCP 툴 1회 호출 → 원문 → ExternalEvent[]
  dedup.py       SeenStore Protocol + InMemory / Jsonl
  inbox.py       ExternalEventInbox — 앱 레벨 단일 큐
  poller.py      ExternalEventPoller — 주기 폴링 → dedup → inbox.put + trigger.fire()
```

레이어 규칙(Hard Rule #1) 준수: 폴러·소스는 `core`, 사고 엔진은 `model_layer`만 의존, UI는 이벤트만 소비. `agent_layer/thought`는 `external_events` 문자열 목록만 받고 MCP를 모른다.

### 데이터 흐름

```
ExternalEventPoller (백그라운드 루프, 소스별 interval)
  → McpToolSource.poll()            # MCP 툴 호출 → 원문 텍스트
  → _derive_events()                # 아이템 분해 + dedup 키 추론
  → SeenStore.filter_new()          # 이미 본 키 제거
  → ExternalEventInbox.put(events)  # payload 적재
  → ExternalTrigger.fire()          # daemon 깨우기 (payload와 분리)

ProactivityDaemon.tick()
  → targets() = 최근 활동순 세션들의 reflect
  → session.reflect()
       · inbox.drain()              # 첫 세션이 전부 소비 → 나머지는 빈 목록(발화 1회)
       · ThoughtRequest(external_events=[...], mode="reflection")
       · 기존 policy 게이팅 → ProactiveMessageEvent
```

`ExternalTrigger.wait()` 시그니처와 `AnyTrigger` race 의미론을 **건드리지 않는다** — payload를 inbox로 분리한 이유다.

## 4. 타입 계약

```python
# core/external/types.py
class ExternalEvent(BaseModel):
    source: str                 # YAML의 소스 이름 (예: "calendar-upcoming")
    key: str                    # dedup 키 ("calendar-upcoming:abc123")
    title: str = ""             # 한 줄 요약 (있으면)
    detail: str = ""            # 원문 (detail_max_chars로 절단)
    occurred_at: str = ""       # best-effort ISO 문자열, 없으면 빈 값

    def as_line(self) -> str:   # 사고 프롬프트에 넣을 한 줄
        ...

# core/external/protocol.py
@runtime_checkable
class ExternalSource(Protocol):
    name: str
    interval_sec: float
    async def poll(self) -> list[ExternalEvent]: ...
```

`ExternalSource`가 Protocol이므로 MCP가 아닌 소스(웹훅·파일 감시·사내 API)도 같은 자리에 꽂힌다.

## 5. YAML 소스 선언

`~/.jarvis/external_sources/*.yaml` — 스케줄러의 `~/.jarvis/schedules/*.yaml` 패턴과 동일.

```yaml
- name: calendar-upcoming
  server: google-calendar        # config의 mcp_servers 이름 참조
  tool: list_events
  args: {time_min: now, time_max: "+2h"}
  interval_sec: 300
  enabled: true

- name: mail-unread
  server: gmail
  tool: search_messages
  args: {q: "is:unread newer_than:1h"}
  interval_sec: 600
```

- 파일이 없으면 소스 0개 → 폴러가 아예 기동하지 않는다(스케줄러와 동일한 무해한 no-op).
- `server`는 [MCPServerConfig](../src/jarvis/config.py) 이름으로 해석한다. **ToolRegistry를 경유하지 않는다** — 서로 다른 서버가 같은 툴 이름을 쓰면 `register_force`로 덮여 충돌하기 때문. `mcp_loader`의 툴 호출 경로를 공개 함수(`call_mcp_tool`)로 노출해 소스가 직접 서버를 지정 호출한다. 서버별 `timeout`이 그대로 적용된다.
- 미지의 서버 이름·필수 필드 누락은 로딩 시 경고 후 그 소스만 skip(다른 소스 로딩을 막지 않음 — MCPToolLoader의 격리 규약과 동일).

## 6. dedup 알고리즘

```python
def derive_events(source: str, raw: str) -> list[ExternalEvent]:
    items = _split_items(raw)           # 아래 규칙
    return [ExternalEvent(source=source, key=_key(source, it), ...) for it in items]

def _split_items(raw):
    # 1) JSON 배열      → 그대로 아이템 목록
    # 2) JSON 객체      → items/events/messages/results/data 중 첫 list 필드
    # 3) 그 외/파싱실패 → 전체 원문 1건
def _key(source, item):
    for f in ("id", "uid", "eventId", "messageId", "threadId"):
        if isinstance(item, dict) and item.get(f):
            return f"{source}:{item[f]}"
    return f"{source}:{sha1(canonical_text(item))[:16]}"
```

`SeenStore`:

| 구현 | 용도 |
|------|------|
| `InMemorySeenStore` | 테스트·휘발 운용 |
| `JsonlSeenStore` | 기본. append-only 로그 replay ([openloop/jsonl_store.py](../src/jarvis/agent_layer/openloop/jsonl_store.py) 패턴 재사용) |

무한 증식 방지: 로드 시 `seen_ttl_sec`(기본 7일) 초과 키를 버리고 최대 `seen_max_keys`(기본 10,000)만 유지.

## 7. 사고 컨텍스트 주입

1. `ThoughtRequest`에 `external_events: list[str] = []` 추가 — 필드 추가는 `think()` 시그니처 불변이라 호출부를 깨지 않는다(계약 주석대로).
2. `DEFAULT_REFLECTION_TEMPLATE`에 `[외부 이벤트] {{external_events}}` 블록 + `PLACEHOLDERS`에 `external_events` 등록.
3. **템플릿 드리프트 방어** — 사용자가 이미 편집한 `~/.jarvis/inner_thought_reflection.md`에는 플레이스홀더가 없다. 이벤트가 있는데 템플릿에 `{{external_events}}`가 없으면 렌더 결과 뒤에 블록을 **append**한다(조용한 유실 방지). `engine._render()`에서 처리.
4. 성찰 템플릿에 판단 지침 한 줄 추가: 외부 이벤트는 사실이지 발화 명령이 아니며, 시급성·관련성이 분명할 때만 act/ask.

여러 이벤트는 **한 번의 성찰로 합쳐진다**(inbox를 한 번에 drain) — 이벤트 N건에 사고 LLM 호출 N번이 나가지 않는다. 틱당 상한은 `max_events_per_tick`(기본 20).

## 8. 세션 라우팅 (drain-once)

- `AgentSession.__init__(..., external_inbox=None)` 주입. `reflect()`가 drain → `_run_inner_thought(..., external_events=...)`.
- **web** — `SessionManager`에 recency가 없으므로 추가한다: `touch(session_id)`(사용자 메시지 수신 지점에서 호출) + `sessions_by_recency()`. daemon targets provider를 이 정렬 목록으로 교체. 한 번도 touch되지 않았으면 기존 삽입 순서로 폴백.
- **TUI** — 세션이 하나라 정렬 자체가 무의미(변경 없음).
- 활성 세션이 0이면 drain하지 않는다 — 이벤트는 inbox에 남아 다음 틱에 소비된다(유실 방지). inbox는 `maxlen` 있는 deque로 상한을 두고, 넘쳐 버린 건수는 로그로 노출한다(조용한 절단 금지).

## 9. 설정

```python
class ExternalTriggerConfig(BaseSettings):
    """외부 트리거(Phase 3). 소스 YAML이 없으면 no-op."""
    enabled: bool = True
    sources_dir: str = "~/.jarvis/external_sources"
    seen_backend: Literal["jsonl", "in_memory"] = "jsonl"
    seen_path: str = "~/.jarvis/external_seen.jsonl"
    seen_ttl_sec: int = 604_800          # 7일
    seen_max_keys: int = 10_000
    max_events_per_tick: int = 20
    detail_max_chars: int = 500          # 프라이버시·토큰 상한
    store_detail_in_log: bool = False    # 사고 로그(LTM)에 원문 detail 저장 여부
```

`daemon_trigger`(interval/idle/both)와는 **직교** — 소스가 있으면 `ExternalTrigger`를 기존 트리거에 `AnyTrigger`로 항상 합성한다. 즉 `daemon_trigger=interval`이어도 외부 이벤트로 깨어난다.

## 10. 배선

| 지점 | 변경 |
|------|------|
| [startup.py](../src/jarvis/ui/tui/startup.py) `_build_infra` | 소스 로딩 → `inbox`/`seen`/`poller` 생성 → `ctx.external_inbox`, `ctx.external_poller`, `_extra["external_inbox"]` |
| `_build_reflection_trigger` | 소스 있으면 `AnyTrigger([...기존, external])` |
| [app.py](../src/jarvis/ui/tui/app.py) `on_mount` / `on_unmount` | `poller.start()` / `stop()` — daemon과 동일한 수명 |
| [server.py](../src/jarvis/ui/web/server.py) startup / shutdown | 동일 + `SessionManager.touch()` / `sessions_by_recency()` |

## 11. 테스트 전략 (실 MCP·실 API 없이)

| 대상 | 방법 |
|------|------|
| `derive_events` | JSON 배열 / 감싼 객체 / 비-JSON / id 없는 아이템 — 키 추론 4경로 |
| `SeenStore` | 최초 통과·재폴링 차단·TTL 만료·max_keys 절단, jsonl replay 왕복 |
| `ExternalEventInbox` | drain-once(두 번째 호출은 빈 목록), maxlen 초과 드롭 카운트 |
| `ExternalEventPoller` | fake source + 주입 clock/sleep → 소스별 주기 준수, 한 소스 예외가 루프를 죽이지 않음, `tick()` 단위 검증 |
| `McpToolSource` | `call_mcp_tool`을 fake로 주입 — 인자 전달·타임아웃·에러 격리 |
| YAML 로더 | 정상·필수필드 누락·미지 서버 이름 → skip + 경고 |
| 사고 주입 | faux provider로 `reflect()` 실행 → 프롬프트에 이벤트 라인 포함, 플레이스홀더 없는 템플릿에도 append 동작 |
| 세션 라우팅 | 세션 2개 + 이벤트 1건 → 발화 1회, 최근 활동 세션이 소비 |
| 게이팅 | 낮은 confidence·쿨다운 내 → silent (기존 policy 경로 재사용 확인) |

## 12. 리스크

| 리스크 | 완화 |
|--------|------|
| **과잉 발화** (최대 리스크) | 기존 threshold·cooldown·피드백 학습 그대로. 성찰 템플릿에 "이벤트는 사실이지 발화 명령이 아니다" 지침 |
| **프라이버시** — 메일 본문이 사고 로그·LTM에 축적 | `detail_max_chars` 절단 + `store_detail_in_log=False` 기본(로그엔 title/key만) |
| 비용·지연 | 이벤트 합쳐 성찰 1회, `max_events_per_tick` 상한, 폴링 주기는 소스별 |
| MCP 서버 무응답 | 서버별 `timeout` 준수 + 소스별 예외 격리(폴러 루프 생존) |
| 사용자 편집 템플릿 유실 | §7-3 append 폴백 |
| seen 스토어 증식 | TTL + max_keys 프루닝 |

## 13. 구현 순서

1. `core/external/` 타입·Protocol·dedup·inbox (순수 로직, 테스트 선행 가능)
2. `mcp_loader.call_mcp_tool` 공개 + `McpToolSource` + YAML 로더
3. `ExternalEventPoller`
4. 사고 주입 (`ThoughtRequest` 필드 · 성찰 템플릿 · `engine._render` append 폴백)
5. 세션 drain + `SessionManager` recency
6. config + startup/app/server 배선
7. 문서 갱신 — [proactive-implementation.md](proactive-implementation.md)의 "미연결(플러그 지점만 마련)" 항목 해소
