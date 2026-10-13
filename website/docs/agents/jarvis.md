---
sidebar_position: 1
title: JARVIS
---

# JARVIS

<span className="agent agent--jarvis">J.A.R.V.I.S.</span> 는 팀 전체를 총괄하는 첫 번째 에이전트다(id `main`). 사용자의 기본 대화 상대이고, 묻기 전에 먼저 생각하고 먼저 말을 건다.

![JARVIS 세션의 Web HUD. 시안 리액터 구체와 AGENDA, ACTIVITY, SYSTEM, SESSIONS, CONVERSATION 카드](/img/agents/jarvis-hud.png)

## 맡은 일

- 사용자의 요청에 답하고, 앱에 등록된 도구(파일, 셸, 웹 검색, MCP, 절차 도구)를 쓴다
- 요청마다 [내적 사고](../concepts/inner-thought.md)로 판단을 남기고, 요청이 없는 시간에는 성찰해서 [먼저 건네는 말](../concepts/proactive.md)을 보낸다
- 대화에서 흘린 [약속](../concepts/agenda.md)을 기억했다가 챙긴다
- 다른 에이전트가 더 잘하는 일은 `ask_agent` 로 맡긴다. 예를 들어 청약 공고 질문은 [KAREN](./karen/index.md)에게 넘긴다

## 하지 않는 것

JARVIS 는 에이전트만 쓰는 도구(`lh_notice`, `sh_notice`, `housing_loan`, `housing_budget`)를 갖지 않는다. 이 도구는 정의 파일의 `tools` 에 이름을 적은 에이전트만 받는다.

## 설정

JARVIS 는 정의 파일 대신 환경 변수가 정본이다. `team/` 에 `main.yaml` 을 두어도 무시한다.

| 항목 | 환경 변수 | 기본값 |
|---|---|---|
| 이름 | `JARVIS_BRAND__NAME` | `J.A.R.V.I.S.` |
| 명언 | `JARVIS_BRAND__QUOTE` | `Proof the Heart` |
| 메인 색 | `JARVIS_BRAND__PALETTE__PRIMARY` | `#5fc8e2` |
| 보조 색 | `JARVIS_BRAND__PALETTE__ACCENT` | `#f0b35f` |
| 모델 | `JARVIS_LLM__*` | [설치 및 실행](../start/install.md)에서 고른 프로바이더 |

다른 에이전트는 비운 항목을 JARVIS 설정에서 이어받는다. 전체 설정 키는 [설정](../reference/configuration.md)에 있다.

## 더 읽을 것

- [최상위 에이전트 팀](../concepts/team.md): 세션, 기억, 승인 규칙을 에이전트끼리 어떻게 나누고 공유하는지
- [기능 목록](../concepts/services.md): JARVIS 가 가진 기능 전체
