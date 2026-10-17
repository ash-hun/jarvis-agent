---
sidebar_position: 0
title: Architecture
---

import FigureArchitecture from '@site/src/figures/architecture.svg';

# Architecture

<figure className="paper-fig">
  <FigureArchitecture />
  <figcaption><b>Figure 1.</b> 계층 구조. 화살표는 의존 방향이다. 아래층은 위층을 모르고, TUI 와 Web 은 app 이 조립한 같은 결과를 받아 화면만 다르게 그린다. memory 는 core 와 agent_layer 가 쓰고, common 의 로거는 어느 층이든 쓴다.</figcaption>
</figure>

JARVIS 는 LLM 추상화, 기억, 에이전트 런타임, 오케스트레이션, 조립, 화면을 층으로 쌓고, 아래층이 위층을 모르게 만든다. TUI 와 Web 두 화면은 같은 조립 결과를 받아 쓰고 화면만 다르다.

## 계층

`src/jarvis/` 의 층은 아래에서 위로 model_layer, memory, agent_layer, core, app, ui 순서다. 아래층은 위층을 모른다. `common/`(로거)은 어느 층이든 쓸 수 있고, 자신은 아무 층도 모른다.

```mermaid
flowchart TB
  subgraph UI["ui/  화면"]
    TUI["tui/  Textual 터미널, startup.py 진입점"]
    WEB["web/  server.py, router/, session_registry.py, 정적 HUD"]
  end
  subgraph APP["app/  조립"]
    INFRA["infra_builder.py  InfraBuilder"]
    PROFILE["agent_profile.py  AgentProfile"]
    SB["session_builder.py  SessionBuilder"]
  end
  subgraph CORE["core/  오케스트레이션과 정책"]
    SESSION["session.py  AgentSession"]
    POLICY["policy/  보안 파이프라인, 샌드박스, 승인 규칙"]
    PROACTIVE["proactive/  daemon, 정책, 피드백"]
    TOOLS["tools/  레지스트리, 내장 도구, MCP"]
    SLASH["slash/  슬래시 커맨드"]
    PROC["procedures/  절차 학습"]
    MULTI["multi_agent/  토폴로지, 오케스트레이터"]
    SCHED["scheduler/  external/  notify/"]
  end
  subgraph AGENT["agent_layer/  에이전트 런타임"]
    HARNESS["harness.py  loop.py  이벤트"]
    THOUGHT["thought/  InnerThoughtEngine, ThoughtFrame"]
    MEMCHAIN["memory/  MemoryMiddlewareChain"]
    OPENLOOP["openloop/  usermodel/  journal/  session/"]
  end
  subgraph MODEL["model_layer/  LLM 추상화"]
    PROVIDERS["providers/  anthropic, openai, gemini, ollama, vllm"]
    STREAM["stream.py  types.py  embeddings.py"]
  end
  MEMORY["memory/  작업 기억, 장기 기억, 회상, 통합"]
  UI --> APP --> CORE --> AGENT --> MODEL
  AGENT --> MEMORY
  CORE --> MEMORY
```

- **model_layer**: 프로바이더마다 `stream()` 하나를 둔다. 텍스트 델타, 도구 호출 델타, 정지 이벤트를 같은 모양으로 낸다. 임베딩도 이 층에 있다
- **agent_layer**: 에이전트 루프(`run_agent_loop`), 세션 저장소, 내적 사고 엔진, 메모리 미들웨어를 가진다. 벤더를 모른다
- **core**: `AgentSession` 이 한 턴을 지휘한다. 보안, 도구, 승인, proactive 정책, 슬래시, 절차 학습, 멀티 에이전트, 스케줄러가 이 층에 있다
- **app**: 조립 층. `InfraBuilder` 가 설정 하나로 도구, 메모리, 저장소, 보안, 스케줄러, proactive, 슬래시 명령을 만들고, `AgentProfile`(에이전트 한 명분 설정과 피드백 학습기)과 `SessionBuilder` 가 세션을 만든다
- **ui**: TUI 와 Web 이 있다. 둘 다 `app` 의 조립 결과(`AppAssembly`)를 받아 화면만 담당한다
- **memory**: `MemoryService` 가 작업 기억(요약과 창)과 장기 기억(의미, 일화, 절차)을 가진다

## 요청 한 번의 흐름

```mermaid
sequenceDiagram
  autonumber
  participant U as 사용자, 화면
  participant S as AgentSession
  participant T as 사고 엔진
  participant H as 하네스, 루프, 메모리
  participant L as LLM
  participant X as 도구, 샌드박스

  U->>S: 입력 (슬래시 명령은 화면 쪽 디스패처가 먼저 처리)
  S->>S: 검증, 인증, 정책, 스킬 펼치기
  S->>T: think(요청). 시점은 before / race / after
  T-->>S: ThoughtFrame (💭 이벤트, open loop 저장)
  S->>H: run(입력, 사고 블록)
  H->>H: 창, 요약, 회상 주입
  loop 최대 20턴
    H->>L: stream(messages, tools)
    L-->>H: 텍스트 또는 도구 호출
    H->>X: 허용 목록, 플러그인, 승인
    X-->>H: 결과 (거부면 is_error)
  end
  H->>H: 세션 저장소에 메시지 저장
  H-->>U: 스트리밍 응답, agent_end
```

다음 세 곳은 순서가 고정이다.

- 보안 파이프라인은 검증, 인증, 정책 순으로 돌고, 어느 단계도 건너뛸 수 없다. 검증은 빈 입력, 길이 상한(기본 10,000자), 스크립트 패턴을 막고 NFC 정규화와 HTML 이스케이프를 한다
- 도구 호출은 정책 허용 목록, 플러그인 `before_tool_call`, 샌드박스 승인 순으로 검사한다. 거부는 예외가 아니라 `is_error` 결과로 LLM 에 돌아가고, 루프는 계속된다
- 메모리 주입은 LLM 호출 직전의 `transform` 한 곳에서만 한다. `[핵심 사실]`, `[장기 기억]`, `[절차 기억]`, `[작업 공유 메모리]`, 요약 순으로 앞에 붙는다

## 이벤트

하네스는 한 턴 동안 아래 이벤트를 구독자에게 보낸다. Web 은 이벤트를 그대로 WebSocket 으로 흘리고, TUI 는 화면 동작으로 번역한다.

| type | 언제 | 주요 필드 |
|---|---|---|
| `agent_start` | 루프 시작 | `agent_name` |
| `turn_start` | 루프의 매 반복 | `turn` |
| `message_update` | 스트리밍 | `text_delta`, `thinking_delta` |
| `tool_execution_start`, `tool_execution_end` | 도구 호출 전후 | `tool_name`, `args`, `is_error` |
| `agent_end` | 루프 끝 | `final_message.usage`, `turns` |
| `agent_error` | 프로바이더 오류 | `message` |
| `inner_thought` | 사고 프레임이 나왔을 때 | `interpretation`, `decision`, `confidence`, `frame` |
| `proactive_message` | filler 또는 먼저 건네는 말 | `text`, `kind`, `message_id` |

## 두 화면, 한 배선

TUI 와 Web 모두 `app/infra_builder.py` 의 `build_app`(도구, 스케줄러, 알림, 서브 에이전트, 디스패처)과 `app/session_builder.py` 의 `SessionBuilder`(사고 엔진, proactive 코어, open loop, 사용자 모델)를 쓴다. 에이전트마다 달라질 수 있는 값(브랜드, 모델, 사고와 proactive 설정, 피드백 학습기)은 `AgentProfile` 에 모여 있고, 지금은 `main` 하나다. Web 은 세션마다 샌드박스와 보안 파이프라인을 따로 두고, 승인은 세션 단위 브로커가 모든 연결에 방송한다. 차이는 화면과 승인 입력 방식뿐이다.

## 저장 위치

JARVIS 가 남기는 데이터는 아래 위치에 저장된다.

| 데이터 | 위치 |
|---|---|
| 세션 대화 | `~/.jarvis/sessions/<id>.jsonl` 또는 Postgres `jarvis_sessions`, `jarvis_entries` |
| 장기 기억 | 메모리 또는 Postgres `jarvis_ltm_entries`(pgvector 선택) |
| 작업 기억 | Postgres `jarvis_working_memory` 또는 메모리 |
| 약속(open loop) | `~/.jarvis/openloops.jsonl` 또는 Postgres `jarvis_open_loops` |
| 승인 기억 | 공용 `~/.jarvis/approvals.yaml`, 에이전트별 `~/.jarvis/approvals/<agent_id>.yaml` |
| 절차 | `~/.jarvis/procedures/<name>.md` |
| 스케줄 | `~/.jarvis/schedules/*.yaml` |
| 사용자 모델 | `~/.jarvis/user_model.json` |
| 사고 템플릿 | `~/.jarvis/inner_thought.md`, `inner_thought_reflection.md` |
| 외부 소스 | `~/.jarvis/external_sources/*.yaml`, 본 것은 `external_seen.jsonl` |

Docker 에서는 `~/.jarvis` 가 `jarvis_data` 볼륨이다.

## 설계 노트

### 조립 층을 따로 둔다

에이전트가 하나일 때는 TUI 시작 코드와 Web 서버가 각자 객체를 조립했다. 최상위 에이전트를 여럿 받으려면 "에이전트 한 명분의 설정" 이 단위가 되어야 해서, 조립만 하는 `app/` 층(AgentProfile, SessionBuilder, SubagentBuilder 등)을 따로 만들었다. 이 정리는 동작을 하나도 바꾸지 않는 것을 조건으로 했다. 테스트는 1053개에서 단위 1167개와 통합 82개로 늘었고, mypy 오류는 777개에서 0개가 됐다.

### 의존은 한 방향

`model_layer` 는 `core` 를 모르고, `agent_layer` 는 화면을 모르고, 화면은 `UIAdapter` 로만 이벤트를 받는다. 그래서 같은 세션이 TUI 와 Web 에 똑같이 붙고, 테스트에서는 실제 LLM 대신 각본 프로바이더(FauxProvider)를 꽂는다. 보안 파이프라인(검증, 인증, 정책, 샌드박스)은 단계마다 구현만 바꿀 수 있고 순서는 바꿀 수 없다.

### 재실행해도 같은 결과

이 프로젝트의 기본 원칙은 멱등성이다. 같은 작업을 두 번 해도 한 번 한 것과 같아야, 중간에 죽었을 때 복구가 "다시 실행" 으로 끝난다. 테이블과 칼럼은 `IF NOT EXISTS` 로 맞추고, 파일은 임시 파일에 쓴 뒤 바꿔 끼우고, 비결정적인 값(시각, id)은 경계에서 만들어 넣는다. 일부러 이 원칙을 어긴 곳에는 `# idempotent:` 마커를, 일부러 단순하게 둔 곳에는 `# ponytail:` 마커를 남겨 나중에 모아 볼 수 있게 했다.

## 구현 위치

왼쪽이 사용자와 화면, 가운데가 코드 모듈, 오른쪽이 저장소다. 화살표는 호출이나 데이터의 방향이다.

```mermaid
flowchart LR
  subgraph UI[화면]
    HUD[Web HUD<br/>app/composer.js]
    TUI[TUI app.py]
    WS["ui/web/router/ws_router.py<br/>ws /ws"]
  end
  subgraph APP[app 조립]
    SB[SessionBuilder<br/>AgentProfile]
  end
  subgraph CORE[core]
    SES[AgentSession<br/>core/session.py]
    SEC[SecurityPipeline<br/>policy/]
    REG[ToolRegistry<br/>tools/]
  end
  subgraph AGENT[agent_layer]
    HAR[AgentHarness]
    LOOP[agent loop<br/>loop.py]
  end
  subgraph MODEL[model_layer]
    PROV[providers<br/>anthropic, openai, gemini, ollama, vllm]
  end
  REPO[(세션 저장소<br/>jsonl, Postgres)]
  HUD --> WS --> SES
  TUI --> SES
  SB -. 세션 조립 .-> SES
  SES --> SEC
  SES --> HAR --> LOOP --> PROV
  LOOP --> REG
  SES --> REPO
  HAR -. 이벤트 .-> WS
```

- 핵심 모듈: `core/session.py`, `agent_layer/loop.py`, `model_layer/`
- 저장: 세션 저장소
