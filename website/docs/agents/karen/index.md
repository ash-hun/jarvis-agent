---
sidebar_position: 0
title: KAREN
---

# KAREN

<span className="agent agent--karen">K.A.R.E.N.</span> 는 정한 분야의 정보를 찾아 모으고 출처와 함께 요약하는 정보 수집 담당 에이전트다(id `karen`). 지금은 LH, SH 청약 공고 조회, 예산에 맞는 공고 추천, 주택 대출 원리금 계산을 맡는다.

![KAREN 세션의 Web HUD. 녹색 리액터 구체와 청약 공고 대화가 보이는 CONVERSATION 카드](/img/agents/karen-hud.png)

## 맡은 일

- 사용자가 정한 분야의 정보를 찾고, 무엇을 어디서 찾았는지 출처와 함께 핵심 3줄에서 5줄로 정리한다
- 확인한 사실과 추측을 나눠 쓰고, 출처가 없는 내용은 "미확인"이라고 적는다
- 청약 공고와 대출 계산은 전용 도구로 처리한다. 쓰는 법은 [청약 공고와 대출 계산](./housing.md)에 있다

## 하지 않는 것

- KAREN 은 혼자 먼저 말을 걸지 않는다(`proactive: false`). 사용자나 다른 에이전트가 부를 때만 일한다
- 공고, 마감, 금액은 이번에 부른 도구 결과에 있는 것만 쓴다. 기억에 남은 공고는 지난 정보로 보고 매번 도구를 먼저 부른다
- 상환액과 이자를 직접 계산하지 않고 `housing_loan` 결과의 숫자를 그대로 쓴다

## 도구

| 도구 | 용도 |
|---|---|
| `lh_notice`, `sh_notice` | LH, SH 청약 공고 조회 |
| `housing_budget` | 총예산과 현금으로 공고 추천 |
| `housing_loan` | 월, 연간 원리금 상환액과 이자 계산 |
| `web_search`, `web_fetch` | 웹 검색과 페이지 읽기 |
| `read_file`, `list_dir`, `glob`, `grep` | 로컬 파일 읽기 |

`ask_agent` 와 `remember_task_pattern` 은 `tools` 에 적지 않아도 모든 에이전트에게 붙는다. KAREN 이 배운 [작업 패턴](../../concepts/memory.md#작업-패턴)은 KAREN 에게만 남는다.

## 정의 파일

KAREN 은 저장소의 `team/karen.yaml` 한 파일로 정의한다. 이름, 설명, 명언(`Eyes on everything`), 메인 색 `#97BC62`, 시스템 프롬프트, 도구 목록이 들어 있고, 비운 항목(모델 등)은 JARVIS 설정을 이어받는다. 파일 형식은 [최상위 에이전트 팀 → 정의 파일](../../concepts/team.md#정의-파일)에 있다.

## 부르는 방법

- Web HUD 의 SESSIONS 카드 위 에이전트 칩에서 KAREN 을 누른다
- TUI 에서 `jarvis --agent karen` 으로 시작한다
- JARVIS 에게 청약 질문을 하면 JARVIS 가 `ask_agent` 로 KAREN 에게 맡긴다
