---
sidebar_position: 1
title: Notice
---

import InfoNotice from '@site/src/figures/info-notice.svg';

# Notice

Jarvis-Agent가 가지는 전체 기능을 정리하고 개발시 고려했던 원칙과 철학을 소개한다. User가 응답 대기시간을 줄이고, 목적에 맞는 업무 보조를 하기 위한 "Personal Agent Runtime Engine"이다.

<figure className="info-fig">
  <InfoNotice />
</figure>

## 개요

### Jarvis-Agent가 주목한 점

기존의 Chatbot Assistant는 사용자의 요청에 의존적이다. 직접 물어보아야만 어떠한 작업이든 시작하게 되며, 오래 걸리는 작업은 사용자가 빈 화면으로 기다리게 된다. 이를 보완하려고 streaming 응답이나 실행 과정을 보여 주는 우회 방안을 쓰기도 하지만, 이는 완전한 해결책이 될 수 없다. Jarvis-Agent는 이러한 부분에서 착안하여 현존하는 Agent Framework의 기능을 모두 포함하면서 조금 더 사용자에 밀접하게 소통하고, 보조할 수 있는 에이전트 엔진을 지향한다.

### 기능 목록

| 기능 | 설명 | 표현방식 |
|---|---|---|
| [Basic Conversation](./conversation/index.md) | 사용자의 요청을 받아 에이전트와 자연스러운 소통을 하게 한다. | 입력창, 음성, TUI |
| [Inner Thought](./conversation/inner-thought.md) | 사용자의 요청을 내재적으로 분석하여 적절히 대응할 수 있게 한다. | 💭 한 줄 |
| [Dual channel](./conversation/proactive.md#dual-channel) | 작업이 오래 걸리는 경우 우선적인 응답을 먼저 한 후(ex, "잠깐만요") background에서 작업을 병렬수행한다. | 💬 filler |
| [Proactive Dialogue](./conversation/proactive.md#성찰과-먼저-건네는-말) | 별도의 사용자 요청이 없더라도 주기적으로 모니터링과정을 거쳐 사용자에게 필요하다 판단되는 요소는 먼저 정보를 제공하도록 한다. | 🔔, Web Push, Slack, Discord |
| [Process Pattern Analysis](./conversation/proactive.md#피드백-학습) | Proactive Dialogue에 대한 수락, 무시, 무응답을 기반으로 발화 임계치를 동적으로 조절한다. | 🔔 뒤 첫 말, `Ctrl+Y`/`Ctrl+G` |
| [Open loop](./conversation/open-loop.md) | 즉각적인 응답이 아닌 특정시점이나 작업 후 공유해야 하는 경우 따로 작업을 기억한다. 이후 해당 작업이 마무리되면 종료한다. | AGENDA, `/openloop` |
| [Scheduling](./conversation/scheduling.md) | 정기적으로 수행해야 하는 작업이나 알람 등을 반복적으로 돌린다 | `/schedule`, AGENDA |
| [MCP Events](./conversation/mcp.md) | 외부 MCP 도구를 주기적으로 불러 사용한다. | 🔔 |
| [Memory Management](./memory.md) | 기본적인 4개 종류의 Memory 관리 방안을 기반으로 적재적소에 사용할 수 있도록 한다. | 사고와 응답의 맥락 |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 내장된 도구와 MCP, 실행 전 승인과 승인 기억, 반복 작업을 절차 도구로 변환하고 사용한다. | 승인 모달, `/procedures` |
| [Sessions](./conversation/sessions.md) | 사용자와의 대화 단위 관리 시스템을 말한다. | SESSIONS 카드, TUI 사이드바 |
| [Multi agent Orchestration](./multi-agent-orchestration/index.md) | 메인 에이전트 외에도 각자의 목적을 가진 Agent를 확장하여 사용한다. 각각의 에이전트마다 세션, 기억, 승인 규칙, 메인 컬러를 따로 갖고 `ask_agent` 로 서로 일을 맡긴다 | 에이전트 칩, AGENDA 라벨, 구체 색 섞임 |
| [Mode](./mode/index.md) | 작업을 수행하는 기본적인 모드전환 시스템을 탑재한다. | 헤더 `DEFAULT` / `FULL-VOICE`, `FOCUS` 표시 |
| [Voice Interface](./conversation/voice.md) | VUI(voice user interface)를 지향하며, 각 에이전트를 전환하면서 작업할 수 있도록 한다. | 구체 클릭, 헤더 `FULL-VOICE` |
| [공용 커맨드](../reference/slash-commands.md) | `/` 명령, 스킬, 플러그인 훅, 사용자 도구 등을 명시적으로 호출하여 사용할 수 있다. | 입력창 `/` |

## 개발 철학

Jarvis-Agent는 원작자가 고안한 아래 구현 및 운영방침을 준수한다.

### 01. Proactive Dialogue를 지향하고, Lazy-Interaction을 최소화한다

사용자를 보좌하는 개인화 비서에게 무엇보다 중요한 것은 가장 사람에 가까운 Communication-Cycle이다. 현대의 에이전트가 가장 취약한 부분 중 하나로, 사용자의 응답대기를 극단적으로 줄이고자 하는 철학을 지닌다. 실제 사람과 사람사이의 소통방식을 고민해보면 잠시 생각하더라도 비언어적인 표현으로라도 상대방에게 신호가 가기 마련이다. 이처럼 에이전트 역시 오래 걸리는 일이라도 바로 반응하고, 알아야 할 일은 묻기 전에 먼저 알릴 수 있도록 설계한다.

- **사고와 응답을 나눈다**: 입력 하나마다 LLM 을 두 번 부른다. 메인 응답은 도구를 쓰고 답을 만든다. 내적 사고는 같은 입력을 보고 의도, 먼저 말할지, 뒤에서 할지를 사고 프레임(`ThoughtFrame`)으로 낸다. 약속이 생겼는지는 따로 도는 AGENDA 판단이 본다. 사고 모델은 메인보다 작고 싸게 둘 수 있고, 사고가 응답을 막지 않도록 시점을 고른다(`before`, `race`, `after`). 기본값 `race` 는 사고를 3초까지만 기다린다. router 모델을 정하면 router 가 요청마다 사고가 필요한지 정하고, 사고 결과는 다음 턴에 넣는다
- **오래 걸릴 일은 먼저 답한다**: 사고가 오래 걸릴 요청으로 판단하면 "잠깐만요" 같은 짧은 답(💬 filler)을 먼저 보내고 메인은 뒤에서 돈다. 사용자는 빈 화면을 보며 기다리지 않는다
- **묻기 전에 먼저 말한다**: 요청이 없어도 주기적으로(기본 120초) 또는 대화가 조용해지면 성찰해서, 다가오는 기한이나 사용자의 일에 영향을 주는 외부 이벤트를 먼저 알린다(🔔)
- **먼저 말하기 전에 게이트를 지난다**: 필요 없는 말은 오히려 사용자를 방해한다. 먼저 건네는 말은 사고 프레임의 `utterance` 만 쓴다. 해석문은 사용자를 3인칭으로 분석한 문장이라 그대로 내보내지 않는다. 발화는 확신도 임계치, 쿨다운, 빈 발화 검사를 전부 지나야 하고, 침묵한 이유는 로그에 남는다. 임계치는 🔔 에 대한 수락, 무시, 무응답으로 사용자에 맞게 움직인다
- **자율 행동은 좁게, 위험한 실행은 사람에게 묻는다**: 저위험 자율 행동은 화이트리스트에 있고 승인도 필요 없는 도구만 실행한다. `bash`, `write_file`, `edit_file` 은 실행 전에 묻고, "항상 허용" 규칙은 사용자가 그 버튼을 눌렀을 때만 생긴다

### 02. 에이전트의 유기적 확장을 지향한다.

특정한 기능을 더하거나 구현을 바꿀 때는 기존 코드를 고치지 않고 붙일 수 있도록 설계하고, 변경가능한 지점을 경계로 나눈다. 또한, 에이전트의 확장을 적극 권장한다.

- **층의 의존 방향을 한쪽으로 둔다**: `model_layer`(LLM 프로바이더, 스트림), `memory`, `agent_layer`(에이전트 루프, 사고), `core`(오케스트레이션, 정책, 도구) 순으로 위 층만 아래 층을 안다. `model_layer` 는 다른 층을 모르고, 사고 층은 벤더 스키마도 MCP 도 모른다. 그래서 한 층을 바꿔도 아래 층은 따라 바뀌지 않는다
- **구현은 설정으로 고른다**: LLM 프로바이더(Anthropic, OpenAI, Gemini, Ollama, vLLM)는 레지스트리에 이름으로 등록하고 설정 값으로 고른다. 메모리(`in_memory`, `postgres`)와 세션 기록(`jsonl`, `postgres`)의 저장소도 설정으로 바꾼다
- **기능은 정해진 지점에 끼운다**: 인증, 권한, 샌드박스는 프로토콜 뒤에 두고 구현을 갈아 끼운다. Focus 모드는 세션 루프를 고치지 않고 턴 앞뒤에 끼어드는 `TurnHook` 으로 붙였고, decision model 은 사고 엔진을 감싸는 래퍼(`DecisionGatedEngine`)로 붙였다
- **코드를 고치지 않고 늘린다**: 최상위 에이전트(KAREN 등)는 정의 파일 하나로 늘어난다. 스킬, 플러그인 훅, 사용자 도구는 `~/.jarvis/` 아래 디렉토리에 두면 기동 때 읽고, 외부 도구는 MCP 서버로 붙인다. 멀티 에이전트 오케스트레이션 패턴(Supervisor, Hierarchical, Market, Blackboard)과 패턴을 이어 붙이는 Pipeline 은 같은 프로토콜(`OrchestratorProtocol`)을 구현한다
- **다시 실행하면 복구된다**: 셋업과 저장은 두 번 해도 한 번 한 것과 같게 만든다(`IF NOT EXISTS`, upsert, 자연 키). 중간에 죽어도 다시 실행하면 되므로, 운영 중에 사람이 상태를 손으로 맞출 일이 없다
- **결정과 부수효과를 나눈다**: 정책은 순수 함수로 두고 I/O 는 경계에서 한다. `uuid4()`, `datetime.now()` 같은 비결정적 값도 경계에서 주입한다. 그래서 먼저 건네는 말의 게이팅을 LLM 없이 데이터셋으로 평가하고, 테스트는 시계를 고정한다.

## Performance Experiments Index

각 기능별 페이지마다 있는 실험의 핵심 숫자를 한눈에 보기 쉽도록 모았다.

| 기능 | 실험 | 핵심 숫자 |
|---|---|---|
| [Inner Thought](./conversation/inner-thought.md) | 사고 시점별 지연 | 로컬 첫 글자 after 2.3초, before 15.6초. 클라우드 after 0.9초 |
| [Inner Thought](./conversation/inner-thought.md) | 사고 프레임 유효성 | gemma4:e2b, gemma4:e4b, gpt-4o-mini 모두 매번 유효 |
| [Inner Thought](./conversation/inner-thought.md) | Thought Router 판정 | 실제 대화 30건에서 think 재현율 1.0, direct 재현율 0.68 |
| [Proactive Dialogue](./conversation/proactive.md) | 게이팅 정책(LLM 없음) | 11사례 precision 1.00, recall 1.00, 오경보 0 |
| [Proactive Dialogue](./conversation/proactive.md) | 말할지 정하기(블라인드) | 새 지시문 recall gpt-4o-mini 0.63 → 0.77, e2b 0.47 → 0.83. decision model tev1, nimble recall 1.00, 오경보 0.30 |
| [Proactive Dialogue](./conversation/proactive.md) | 판정 먼저, 앵커, 사실 계산(3단 라벨) | 시험용 26사례 AUC 0.80 → 0.93, 오경보 0.42 → 0.33(recall 1.00 → 0.97), 사고 LLM 호출 1.13 → 0.77 |
| [Process Pattern Analysis](./conversation/proactive.md) | 짧은 답 분류 | 세 모델 모두 0.9 초과 |
| [Open loop](./conversation/open-loop.md) | 같은 약속 가르기 | bge-m3 와 0.85 문턱에서 정확도 0.83, 잘못 합침 0. nomic-embed-text 0.61, 글자 규칙만 0.56 |
| [Memory Management](./memory.md) | 기능 스위트 | 68사례 모두 통과, 다른 범위로 새는 비율 0.00. retention 컨텍스트 117,786자 → 14,129자 |
| [Memory Management](./memory.md) | 오래된 큰 기억 회상 | 새 일화 40개 뒤에도 100%(이전 코드는 3개 뒤 0%). 회상 p50 2.3 ms → 7.3 ms |
| [Memory Management](./memory.md) | 요약 언어 | 예전 지시문은 한국어 대화를 27번 중 20번 영어로 요약. 지금은 세 모델 모두 9번 다 한국어. 사실 보존 1.00 |
| [Memory Management](./memory.md) | 원문 검색(RAG) 대비 순이득 | LongMemEval-s 정답률 RAG 0.57, Jarvis 0.43(출처 회상 0.52). PersonaMem-v2, MINT-Eval 도 RAG 아래. 실서비스 조건 0.28 → 0.50 |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 거부 뒤 승인 흐름 | gpt-4o-mini, gemma4:e4b 모두 3번 중 3번 준수(프롬프트 규칙만일 때 거부 직후 문구 2번 중 0번) |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 음성 승인 답 분류 | 위험한 허용 0. 결정 정확도 e4b 1.0, e2b 0.917, gpt-4o-mini 0.75 |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 실패 반성(BBEH-mini), 절차 수렴 | held-out 0.158 → 0.163(잡음 범위). 성공 30회 뒤 절차 파일 10개 → 1개 |
| [Multi agent Orchestration](./multi-agent-orchestration/index.md) | JARVIS 가 KAREN 에게 맡기기 | 두 모델 모두 세 번 다 위임. 끝까지 gemma4:e4b 36.48초, gpt-4o-mini 8.48초 |
| [Focus Mode](./mode/focus-mode.md) | 첫 응답 시간 | gemma4:e4b 19.47~20.08초, gpt-4o-mini 2.77~2.89초 |
| [Focus Mode](./mode/focus-mode.md) | 조사 형식 | 선례 3개 이하 gemma4:e4b 2/4, gpt-4o-mini 4/4. 번호 목록 없음 두 모델 모두 4/4 |
| [Voice Interface](./conversation/voice.md) | 영어 답의 첫 소리 | 조각마다 1.2~2.2초, 한 번에 합성 2.6~7.8초 |
| [Voice Interface](./conversation/voice.md) | 실제 전사 기록에서 Focus 키워드 해석 | 종료 시도 2번이 고친 뒤 모두 `/focus stop`(고치기 전 모두 대화로 감). 시작 시도 3번은 고친 뒤에도 시작으로 잡히지 않음 |
| [Voice Interface](./conversation/voice.md) | Qwen3-TTS 복제 음성 품질 | UTMOS 4.07, WER 0.017, 화자 유사도 0.965(Piper 파인튜닝 2.6~2.9, 사람 녹음 4.1) |
| [Architecture](./architecture.md) | 요청 한 번의 모델 밖 처리 시간 | 초반 턴 2.65ms, JSONL 기록 읽기가 200턴째 13.7ms 로 커짐(메모리 저장소 1.07ms) |
| [Architecture](./architecture.md) | 넘침 이어가기(KramaBench) | 답을 낸 비율 10% → 100%, 정답률은 차이 없음(0.000 → 0.075, 넘치지 않은 과제 1건) |
| [Sessions](./conversation/sessions.md) | 삭제와 다시 열기가 겹칠 때 | 세션별 잠금 전 18.1% 가 기록 없이 세션만 남음, 잠금 뒤 0% |
| [Scheduling](./conversation/scheduling.md) | 알림 실패 때 놓친 공고 | 알림 실패율 30% 에서 29.4% 가 0% 로, 두 번 알림 0건 |
| [MCP Events](./conversation/mcp.md) | 전하지 못한 외부 이벤트 | 사고 실패율 50%, 주기마다 5건에서 48.3% 가 0% 로 |
| [Orchestration Pattern](./multi-agent-orchestration/orchestration-pattern.md) | 패턴별 걸린 시간 | blackboard 0.201초, hierarchical 0.604초, 한 턴에 하나씩 부르는 감독자 1.829초 |
| [Extension](./extension.md) | 도구 파일 반영 시간 | 새 파일 p50 77.1ms, 고친 파일 p50 78.0ms. 감시 전에는 재시작 필요 |

