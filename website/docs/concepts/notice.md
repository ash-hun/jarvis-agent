---
sidebar_position: 1
title: Notice
---

import InfoNotice from '@site/src/figures/info-notice.svg';
import FigureExpScorecard from '@site/src/figures/exp-scorecard.svg';

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
| [Basic Conversation](./conversation/index.md) | 사용자의 요청을 받아 에이전트와 자연스러운 소통을 하게 한다. | 입력창, 음성 |
| [Inner Thought](./conversation/inner-thought.md) | 사용자의 요청을 내재적으로 분석하여 적절히 대응할 수 있게 한다. | 💭 한 줄 |
| [Dual channel](./conversation/proactive.md#dual-channel) | 작업이 오래 걸리는 경우 우선적인 응답을 먼저 한 후(ex, "잠깐만요") background에서 작업을 병렬수행한다. | 💬 filler |
| [Proactive Dialogue](./conversation/proactive.md#성찰과-먼저-건네는-말) | 별도의 사용자 요청이 없더라도 주기적으로 모니터링과정을 거쳐 사용자에게 필요하다 판단되는 요소는 먼저 정보를 제공하도록 한다. | 🔔, Web Push, Slack, Discord |
| [Process Pattern Analysis](./conversation/proactive.md#피드백-학습) | Proactive Dialogue에 대한 수락, 무시, 무응답을 기반으로 발화 임계치를 동적으로 조절한다. | 🔔 뒤 첫 말, `Ctrl+Y`/`Ctrl+G` |
| [Open loop](./conversation/open-loop.md) | 즉각적인 응답이 아닌 특정시점이나 작업 후 공유해야 하는 경우 따로 작업을 기억한다. 이후 해당 작업이 마무리되면 종료한다. | AGENDA, `/openloop` |
| [Scheduling](./conversation/scheduling.md) | 정기적으로 수행해야 하는 작업이나 알람 등을 반복적으로 돌린다 | `/schedule`, AGENDA |
| [MCP Events](./conversation/mcp.md) | 외부 MCP 도구를 주기적으로 불러 사용한다. | 🔔 |
| [Memory Management](./memory.md) | 기본적인 4개 종류의 Memory 관리 방안을 기반으로 적재적소에 사용할 수 있도록 한다. | 사고와 응답의 맥락 |
| [Tool & Approve System](./conversation/tools-and-approval.md) | 내장된 도구와 MCP, 실행 전 승인과 승인 기억, 반복 작업을 절차 도구로 변환하고 사용한다. | 승인 모달, `/procedures` |
| [Sessions](./conversation/sessions.md) | 사용자와의 대화 단위 관리 시스템을 말한다. | SESSIONS 카드 |
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

### Jarvis Scorecard

Jarvis-Agent 의 대표 성능을 벤치마크 9개로 잰다. 꼭짓점 하나가 벤치마크 하나이고, 바깥 호가 능력 축이며, 다각형 하나가 메인 LLM 하나다. 모든 다각형은 같은 표본, 같은 seed, 같은 판정자(gpt-4o), 같은 기억 생성 모델(gpt-4o-mini), 같은 임베딩(bge-m3)을 쓰고, 바뀌는 것은 메인 LLM 과 같은 계열의 사고 모델뿐이다.

<figure className="paper-fig">
  <FigureExpScorecard />
  <figcaption><b>Figure 1.</b> 점수는 모두 0~100 이다. 면적과 합산 점수는 꼭짓점 순서에 따라 바뀌므로 내지 않는다.</figcaption>
</figure>

| 축 | 꼭짓점 | 점수 | claude-sonnet-5-5 | gpt-4o-mini | gemma4:e4b | 표본 |
|---|---|---|---|---|---|---|
| Personalization | PersonaMem-v2 | 정확도 | 46.7 (34.6~59.1) | 31.7 (21.3~44.2) | 18.3 (10.6~29.9) | 60 |
| Proactivity | ProactiveBench | (recall + 1 − 오경보) / 2 | 50.0 (40.4~59.6) | 69.0 (59.4~77.2) | 69.9 (60.3~78.0) | 100 |
| Proactivity | Custom Scenario Test | (recall + 1 − 오경보) / 2 | 100.0 (86.2~100.0) | 88.9 (70.7~96.4) | 66.6 (46.7~82.0) | 24 × 3회 |
| Tool Use | τ²-bench | pass^1 | 87.5 (73.9~94.5) | 32.5 (20.1~48.0) | 35.0 (22.1~50.5) | 40 |
| Tool Use | GAIA | 정답 일치율 | 70.0 (54.6~81.9) | 37.5 (24.2~53.0) | 25.0 (14.2~40.2) | 40 |
| Long-Horizon | KramaBench | 공식 채점 평균 | 55.0 (34.2~74.2) | 15.0 (5.2~36.0) | 7.6 (1.8~27.1) | 20 |
| Self-Evolving | BBEH-mini | 반성 뒤 held-out 정확도 | 57.1 (49.8~64.0) | 16.3 (11.7~22.3) | 17.9 (13.1~24.1) | 184 |
| Memory Performance | LongMemEval-s | 판정 정확도 | 53.3 (40.9~65.4) | 51.7 (39.3~63.8) | 48.3 (36.2~60.7) | 60 |
| Memory Performance | MINT-Eval | 정확도 | 5.0 (1.4~16.5) | 7.5 (2.6~19.9) | 15.0 (7.1~29.1) | 40 |

괄호는 Wilson 95% 구간이다. 반복 측정(Custom Scenario Test)도 구간의 n 은 사례 수로 잡았다.

- **설정**: 사고 모델은 claude-haiku-5-5, gpt-4o-mini, gemma4:e2b 다. Proactivity 두 꼭짓점은 사고 모델이 decision model 없이 직접 정하는 기본 구성이다. ProactiveBench 는 확신도 눈금이 모델마다 달라, 시험 표본에 들지 않은 32 사건으로 모델마다 임계치를 골라 썼다(gpt-4o-mini, gemma4:e2b 0.8, claude-haiku-5-5 0.9). Custom Scenario Test 는 운영 기본 0.85 다. 기억 꼭짓점 셋은 실서비스 조건(핵심 사실과 회상 각 3개, 출처 회상 켬)이다. τ²-bench, GAIA, KramaBench 는 운영 에이전트 루프(기본 max_turns, 넘침 이어가기 켬)로 풀었다. τ²-bench 의 사용자 역할도 gpt-4o 가 맡는다
- **결과**: Claude 다각형은 gemma 보다 6 꼭짓점(PersonaMem-v2, Custom Scenario Test, τ²-bench, GAIA, KramaBench, BBEH-mini)에서 구간이 겹치지 않게 높고, ProactiveBench 에서는 gemma 가 구간이 겹치지 않게 높다. gpt-4o-mini 와 비교하면 τ²-bench, GAIA, BBEH-mini 에서만 구간이 겹치지 않는다. gpt-4o-mini 와 gemma 사이에는 구간이 겹치지 않는 꼭짓점이 없다. LongMemEval-s 는 세 모델이 48~53 으로 거의 같다
- **해석**: ProactiveBench 에서 claude-haiku-5-5 는 100 사건 모두 침묵을 골랐고 확신도도 0.1~0.3 이었다. 임계치를 낮춰도 말하지 않아 50점은 "늘 침묵" 의 값이다. 고정 임계치 0.85 에서는 gpt-4o-mini 도 50점이었지만(말하겠다고 한 41건의 확신도가 가장 높아도 0.8), 보정 뒤 69.0 이 되었다. 한국어로 만든 Custom Scenario Test 에서는 Claude 가 3회 모두 말할 때 말하고 참을 때 참았다. BBEH-mini 의 반성 효과는 모델마다 작다. claude-sonnet-5-5 는 반성 전 55.4 에서 57.1(새로 맞힌 11, 놓친 8), gemma4:e4b 는 22.3 에서 17.9(새로 맞힌 4, 놓친 12)였다
- **판정자 편향**: 판정 LLM 을 쓰는 LongMemEval-s, MINT-Eval 의 답을 다른 계열인 claude-sonnet-5-5 로 다시 채점했다. 두 판정의 일치율은 93~100%, Cohen's kappa 는 0.63~1.00 이었다. Claude 판정자가 세 모델 모두에 조금 더 엄격했고(0~3.3점 낮음) 순위는 그대로였다. gpt-4o 가 같은 계열인 gpt-4o-mini 를 봐준다는 근거는 보이지 않았다. τ²-bench 의 사용자 역할(gpt-4o)은 다시 돌려야 해서 확인하지 않았다
- **한계**: 표본이 20~60 이라 구간이 넓다. 모델 등급이 같지 않아(상위 모델, 소형 모델, 로컬 소형 모델) 이 그림은 회사 사이가 아니라 세 구성 사이의 비교다. Anthropic SDK 가 temperature 를 받지 않아 Claude 만 temperature 0 이 아니다(결과는 캐시해 재실행은 같다). ProactiveBench 는 공식 보상 모델이 공개되지 않아 사람 라벨로 "말할지" 만 채점한다. Custom Scenario Test 의 라벨은 아직 사람이 검수하지 않았다. τ²-bench 는 정보 전달 여부를 공식의 문자열 포함 옵션으로 본다. GAIA 는 DuckDuckGo 검색이라 검색 결과가 실행마다 다를 수 있다. GAIA 문항과 정답은 이용 조건에 따라 저장소에 두지 않는다
- **넘침 문구 수정**: 넘침 정리 문구가 한국어라 영어 요청에도 한국어 답이 나왔다(캐시에서 GAIA 8건, KramaBench 52건). 정리와 이어가기 지시가 원래 요청의 언어와 답 형식을 따르게 고친 뒤, 넘쳤던 풀이만 다시 풀었다. GAIA 는 gpt-4o-mini 가 32.5 → 37.5, claude-sonnet-5-5 가 60.0 → 70.0 이 되었다(Claude 는 요청 제한으로 캐시되지 않았던 4문항도 다시 풀었다)
- **비용**: claude-sonnet-5-5 다각형이 Anthropic 에서 낸 비용은 다시 잰 것까지 모두 약 $38 이다(BBEH-mini $13.38, 첫 GAIA $11.71, 다시 푼 GAIA $6.09, τ²-bench $2.98, KramaBench $1.47, 나머지 $2.3). 견적은 gpt-4o-mini 실측 토큰으로 냈다. 에이전트 루프는 프롬프트 캐시 덕에 견적보다 적게 썼고(KramaBench), 출력이 긴 BBEH-mini 는 견적보다 많이 썼다
- **재현**: `uv run python -m scripts.experiments.jarvis_scorecard --polygon gpt gemma claude`, 판정자 편향은 `uv run python -m scripts.experiments.scorecard_judge_bias`. 꼭짓점 결과는 `~/.jarvis/benchmarks/scorecard/` 에 캐시해 다시 돌리면 읽기만 한다. 설정은 `scripts/experiments/scorecard_config.json`

### 기능별 실험

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

## 참고 문헌

스코어카드가 쓰는 벤치마크다.

- Bowen Jiang, Yuan Yuan, Maohao Shen, et al. 2025. PersonaMem-v2: Towards Personalized Intelligence via Learning Implicit User Personas and Agentic Memory. [arXiv:2512.06688](https://arxiv.org/abs/2512.06688)
- Yaxi Lu 외. Proactive Agent: Shifting LLM Agents from Reactive Responses to Active Assistance. [arXiv:2410.12361](https://arxiv.org/abs/2410.12361). ProactiveBench: [thunlp/ProactiveAgent](https://github.com/thunlp/ProactiveAgent)
- τ²-bench: [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)
- GAIA: [gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA)
- KramaBench: [eugenie-y/KramaBench](https://huggingface.co/datasets/eugenie-y/KramaBench)
- Kazemi 외. 2025. BIG-Bench Extra Hard. [arXiv:2502.19187](https://arxiv.org/abs/2502.19187)
- Di Wu, Hongwei Wang, Wenhao Yu, Yuwei Zhang, Kai-Wei Chang, Dong Yu. 2025. LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory. [arXiv:2410.10813](https://arxiv.org/abs/2410.10813)
- Hyunji Lee, Justin Chih-Yao Chen, Joykirat Singh, Zaid Khan, Elias Stengel-Eskin, Mohit Bansal. 2026. MINTEval: Evaluating Memory under Multi-Target Interference in Long-Horizon Agent Systems. [arXiv:2605.18565](https://arxiv.org/abs/2605.18565)
- Xuan He, Sining Zhoubian, Ruozhen Yang, et al. 2026. Memory Tax: Dissecting the Net Value of Agent Memory. [arXiv:2610.34073](https://arxiv.org/abs/2610.34073). 모델 비교의 판정자와 기억 생성을 고정한 근거
