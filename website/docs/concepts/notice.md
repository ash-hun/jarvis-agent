---
sidebar_position: 1
title: Notice
---

# Notice

Jarvis-Agent의 기능을 정리하고 어떤 원칙으로 구현되었는지 소개한다.

## 기능 목록

| 기능 | 무엇을 하나 | 쓰는 곳 |
|---|---|---|
| [Basic Conversation](./architecture/index.md) | 메시지를 받아 LLM 과 도구를 오가며 답한다. 스트리밍, 중단, 프로바이더 교체 | 입력창, 음성, TUI |
| [Inner Thought](./architecture/inner-thought.md) | 메인 응답과 분리된 호출로 해석, 결정, 확신도, 약속을 만든다 | 💭 한 줄 |
| [Dual channel](./architecture/proactive.md#dual-channel) | 오래 걸릴 요청이면 "잠깐만요" 를 먼저 말하고 메인은 뒤에서 돈다 | 💬 filler |
| [Proactive Dialogue](./architecture/proactive.md#성찰과-먼저-건네는-말) | 요청이 없어도 주기적으로 성찰해 가치가 분명할 때만 먼저 말한다 | 🔔, Web Push, Slack, Discord |
| [Process Pattern Analysis](./architecture/proactive.md#피드백-학습) | 🔔 에 대한 수락, 무시, 무응답으로 발화 임계치를 움직인다. 키워드가 아닌 답은 사고 모델이 분류한다 | 🔔 아래 질문, `Ctrl+Y`/`Ctrl+G` |
| [Open loop](./conversation/open-loop.md) | 대화에서 흘린 약속을 기억하고, 끝나거나 취소되거나 기한이 지나면 닫는다 | AGENDA, `/openloop` |
| [Scheduling](./conversation/scheduling.md) | 한 번, 마감까지 반복, cron 으로 알림이나 작업을 돌린다 | `/schedule`, AGENDA |
| [MCP Events](./conversation/mcp.md) | MCP 도구를 주기적으로 불러 새 항목을 성찰에 먹인다 | 🔔 |
| [Memory Management](./memory.md) | 작업 메모리, 일화, 의미, 절차 기억, 에이전트별 작업 패턴(사용자가 알려 준 방식). 회상, 통합, 임베딩 | 사고와 응답의 맥락 |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 내장 도구와 MCP, 실행 전 승인과 승인 기억, 반복 작업을 절차 도구로 | 승인 모달, `/procedures` |
| [Sessions](./conversation/sessions.md) | 대화 단위. 만들기, 전환, 분기, 이어 붙이기 | SESSIONS 카드, TUI 사이드바 |
| [Multi agent Orchestration](./multi-agent-orchestration/index.md) | JARVIS 와 같은 층의 에이전트(KAREN 등)를 파일 하나로 늘린다. 세션, 기억, 승인 규칙, 색을 따로 갖고 `ask_agent` 로 서로 일을 맡긴다 | 에이전트 칩, AGENDA 라벨, 구체 색 섞임 |
| [Mode](./mode/index.md) | 음성 축(Default, Full-voice)과 작업 축(Focus)을 따로 골라 겹쳐 쓴다 | 헤더 `DEFAULT` / `FULL-VOICE`, `FOCUS` 표시 |
| [Voice Interface](./conversation/voice.md) | 음성 입력과 읽기. Full-voice 는 응답, 승인, 🔔 피드백까지 말로 묻고 답한다 | 구체 클릭, 헤더 `FULL-VOICE` |
| [공용 커맨드](../reference/slash-commands.md) | `/` 명령, 스킬, 플러그인 훅, 사용자 도구 | 입력창 `/` |

## 구현 철학

Jarvis-Agent는 구현 및 운영부문에 아래 원칙을 지킨다.

### Proactive Dialogue를 지향하고, Lazy-Interaction을 최소화한다

사용자가 답을 기다리는 시간을 줄이는 것이 목표다. 물었을 때는 오래 걸리는 일이라도 바로 반응하고, 알아야 할 일은 묻기 전에 먼저 알린다.

- **사고와 응답을 나눈다**: 입력 하나마다 LLM 을 두 번 부른다. 메인 응답은 도구를 쓰고 답을 만든다. 내적 사고는 같은 입력을 보고 의도, 먼저 말할지, 뒤에서 할지, 약속이 생겼는지를 사고 프레임(`ThoughtFrame`)으로 낸다. 사고 모델은 메인보다 작고 싸게 둘 수 있고, 사고가 응답을 막지 않도록 시점을 고른다(`before`, `race`, `after`). 기본값 `race` 는 사고를 3초까지만 기다린다
- **오래 걸릴 일은 먼저 답한다**: 사고가 오래 걸릴 요청으로 판단하면 "잠깐만요" 같은 짧은 답(💬 filler)을 먼저 보내고 메인은 뒤에서 돈다. 사용자는 빈 화면을 보며 기다리지 않는다
- **묻기 전에 먼저 말한다**: 요청이 없어도 주기적으로(기본 120초) 또는 대화가 조용해지면 성찰해서, 다가오는 기한이나 사용자의 일에 영향을 주는 외부 이벤트를 먼저 알린다(🔔)
- **먼저 말하기 전에 게이트를 지난다**: 필요 없는 말은 오히려 사용자를 방해한다. 먼저 건네는 말은 사고 프레임의 `utterance` 만 쓴다. 해석문은 사용자를 3인칭으로 분석한 문장이라 그대로 내보내지 않는다. 발화는 확신도 임계치, 쿨다운, 빈 발화 검사를 전부 지나야 하고, 침묵한 이유는 로그에 남는다. 임계치는 🔔 에 대한 수락, 무시, 무응답으로 사용자에 맞게 움직인다
- **자율 행동은 좁게, 위험한 실행은 사람에게 묻는다**: 저위험 자율 행동은 화이트리스트에 있고 승인도 필요 없는 도구만 실행한다. `bash`, `write_file`, `edit_file` 은 실행 전에 묻고, "항상 허용" 규칙은 사용자가 그 버튼을 눌렀을 때만 생긴다

### 확장 가능한 아키텍처 설계

기능을 더하거나 구현을 바꿀 때 기존 코드를 고치지 않고 붙일 수 있도록, 바뀔 수 있는 지점을 경계로 나눈다.

- **층의 의존 방향을 한쪽으로 둔다**: `model_layer`(LLM 프로바이더, 스트림), `memory`, `agent_layer`(에이전트 루프, 사고), `core`(오케스트레이션, 정책, 도구) 순으로 위 층만 아래 층을 안다. `model_layer` 는 다른 층을 모르고, 사고 층은 벤더 스키마도 MCP 도 모른다. 그래서 한 층을 바꿔도 아래 층은 따라 바뀌지 않는다
- **구현은 설정으로 고른다**: LLM 프로바이더(Anthropic, OpenAI, Gemini, Ollama, vLLM)는 레지스트리에 이름으로 등록하고 설정 값으로 고른다. 메모리(`in_memory`, `postgres`)와 세션 기록(`jsonl`, `postgres`)의 저장소도 설정으로 바꾼다
- **기능은 정해진 지점에 끼운다**: 인증, 권한, 샌드박스는 프로토콜 뒤에 두고 구현을 갈아 끼운다. Focus 모드는 세션 루프를 고치지 않고 턴 앞뒤에 끼어드는 `TurnHook` 으로 붙였고, decision model 은 사고 엔진을 감싸는 래퍼(`DecisionGatedEngine`)로 붙였다
- **코드를 고치지 않고 늘린다**: 최상위 에이전트(KAREN 등)는 정의 파일 하나로 늘어난다. 스킬, 플러그인 훅, 사용자 도구는 `~/.jarvis/` 아래 디렉토리에 두면 기동 때 읽고, 외부 도구는 MCP 서버로 붙인다. 멀티 에이전트 오케스트레이션 패턴(Supervisor, Hierarchical, Market, Blackboard)과 패턴을 이어 붙이는 Pipeline 은 같은 프로토콜(`OrchestratorProtocol`)을 구현한다
- **다시 실행하면 복구된다**: 셋업과 저장은 두 번 해도 한 번 한 것과 같게 만든다(`IF NOT EXISTS`, upsert, 자연 키). 중간에 죽어도 다시 실행하면 되므로, 운영 중에 사람이 상태를 손으로 맞출 일이 없다
- **결정과 부수효과를 나눈다**: 정책은 순수 함수로 두고 I/O 는 경계에서 한다. `uuid4()`, `datetime.now()` 같은 비결정적 값도 경계에서 주입한다. 그래서 먼저 건네는 말의 게이팅을 LLM 없이 데이터셋으로 평가하고, 테스트는 시계를 고정한다

### Code Convention

- 모듈은 기능 단위(`openloop/`, `procedures/`)로 나눈다. 종류별(`utils.py`, `services.py`)로 나누지 않는다
- `class` 는 유지할 상태나 주입할 의존성이 있을 때만 쓰고, 없으면 함수로 쓴다
- 주석에는 왜(why)만 적는다. 설명이 코드보다 길면 설명을 지운다
- 작업을 끝내기 전에 "이걸 지금 한 번 더 실행하면 어떻게 되나" 에 말로 답할 수 있어야 한다
