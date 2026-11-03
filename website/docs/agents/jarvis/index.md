---
sidebar_position: 0
title: JARVIS
---

# JARVIS

<span className="agent agent--jarvis">J.A.R.V.I.S.</span> 는 팀 전체를 총괄하는 첫 번째 에이전트다(id `main`). 사용자의 기본 대화 상대이면서, 다른 에이전트가 더 잘하는 일은 나눠 맡기는 창구 역할을 한다. 묻는 말에 답하는 데서 그치지 않고, 묻기 전에 먼저 생각하고 필요하면 먼저 말을 건다.

![JARVIS 세션의 Web HUD. 시안 리액터 구체와 AGENDA, ACTIVITY, SYSTEM, SESSIONS, CONVERSATION 카드](/img/agents/jarvis-hud.png)

## 맡은 일

- 사용자의 요청에 답하고, 앱에 등록된 도구(파일, 셸, 웹 검색, 알림 예약, 목표, MCP, 절차 도구)를 쓴다. 도구 목록은 [JARVIS 도구](./tools.md)에 있다
- 요청마다 판단을 남기고([Inner Thought](../../concepts/conversation/inner-thought.md)), 요청이 없는 시간에는 성찰해서 먼저 말을 건넨다([Proactive Dialogue](../../concepts/conversation/proactive.md))
- 대화에서 흘린 약속을 기억했다가 챙긴다([Open loop](../../concepts/conversation/open-loop.md))
- 다른 에이전트가 더 잘하는 일은 `ask_agent` 로 맡긴다. 예를 들어 청약 공고 질문은 [KAREN](../karen/index.md)에게 넘긴다

## 개성

말투는 `JARVIS_BRAND__PERSONA` 로 바꿀 수 있고, 기본값은 `jarvis_config.py` 의 `DEFAULT_PERSONA` 다. 대화 답변, 먼저 건네는 말, filler 에 같이 쓰인다.

- 모든 답과 먼저 건네는 말에 "Sir" 를 붙인다. 예: "Sir, 3시 회의 10분 전입니다."
- 지시받은 것에 필요한 답만 한다. 결론과 숫자를 먼저 말하고 묻지 않은 설명, 일반론, 대안은 붙이지 않는다
- 사람이 말하듯 구어체로 답한다. 번호 목록, 불릿, 표를 쓰지 않고 문장으로 잇는다. 예: "Sir, 내일 오전엔 운동하시고 보고서 쓰시면 됩니다."
- 대화에 사용자의 반복되는 패턴이 보일 때만 그 패턴을 짚는 건조한 농담을 한마디 곁들인다. 잔소리나 걱정으로 대신하지 않는다. 예: 이번 주 네 번째로 "내일은 꼭 운동한다"는 말에 "Sir, 그 말씀은 이번 주에만 네 번째로 받아 적습니다."

`JARVIS_VOICE__SPEAK_ENGLISH=true` 면 소리로 읽는 말은 영어로 옮겨 JARVIS 목소리로 읽는다([Voice Interface](../../concepts/conversation/voice.md#jarvis-가-하는-말은-모두-jarvis-목소리로)).

## 하지 않는 것

JARVIS 는 에이전트만 쓰는 도구(`lh_notice`, `sh_notice`, `housing_loan`, `housing_budget`, `housing_profile`, `housing_watch`)를 갖지 않는다. 이 도구는 정의 파일의 `tools` 에 이름을 적은 에이전트만 받는다. 그래서 청약 질문은 직접 답하지 않고 `ask_agent` 로 KAREN 에게 맡긴다.

## 도구

JARVIS 는 정의 파일이 없어 도구 목록이 비어 있고, 그래서 앱에 등록된 도구 전체를 쓴다. 셸과 파일 쓰기처럼 권한이 큰 도구를 기본으로 가진 에이전트는 JARVIS 하나다. 내장 도구, 설정에 따라 붙는 도구, 모든 에이전트가 함께 쓰는 도구는 [JARVIS 도구](./tools.md)에 정리했다.

## 설정

JARVIS 는 정의 파일 대신 환경 변수가 정본이다. `team/` 에 `main.yaml` 을 두어도 무시한다.

| 항목 | 환경 변수 | 기본값 |
|---|---|---|
| 이름 | `JARVIS_BRAND__NAME` | `J.A.R.V.I.S.` |
| 명언 | `JARVIS_BRAND__QUOTE` | `Proof the Heart` |
| 메인 색 | `JARVIS_BRAND__PALETTE__PRIMARY` | `#5fc8e2` |
| 보조 색 | `JARVIS_BRAND__PALETTE__ACCENT` | `#f0b35f` |
| 모델 | `JARVIS_LLM__*` | [Quick Start](../../start/install.md)에서 고른 프로바이더 |

다른 에이전트는 비운 항목을 JARVIS 설정에서 이어받는다. 전체 설정 키는 [서비스 설정 값](../../reference/configuration.md)에 있다. 세션, 기억, 승인 규칙을 에이전트끼리 어떻게 나누고 공유하는지는 [Multi agent Orchestration](../../concepts/multi-agent-orchestration/index.md)에, JARVIS 가 가진 기능 전체는 [Notice](../../concepts/notice.md)에 있다.

## 부르는 방법

- `jarvis` 로 띄우고 Web HUD 나 데스크톱 앱을 열면 JARVIS 와 대화한다
- 에이전트가 둘 이상이면 Web HUD 리액터 구체 양옆의 화살표를 누르거나 구체를 좌우로 밀어 J.A.R.V.I.S. 로 돌아온다
