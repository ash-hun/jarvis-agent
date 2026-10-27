---
sidebar_position: 1
title: 새로운 Agent 확장방법
---

# 새로운 Agent 확장방법

JARVIS 와 같은 층에 에이전트를 하나 더 둔다. 코드를 고치지 않고 정의 파일 하나로 늘린다. 에이전트마다 자기 세션, 기억, 약속, 승인 규칙, 메인 색을 가진다. 동작 원리는 [Multi agent Orchestration](../concepts/multi-agent-orchestration/index.md)에 있다.

## 정의 파일 만들기

팀 디렉터리에 `<id>.yaml` 파일을 하나 만든다. 파일 이름이 에이전트 id 가 된다.

| 실행 방식 | 팀 디렉터리 |
|---|---|
| 로컬 (uv) | `~/.jarvis/team` |
| Docker | 저장소의 `team/` (컨테이너의 `/app/team`) |

다른 위치를 쓰려면 `JARVIS_TEAM__DIR` 을 바꾼다.

id 는 `^[a-z][a-z0-9_-]{0,31}$` 를 따라야 한다. 소문자로 시작하고 32자 이하다. 세션, 기억, 승인 파일 이름에 그대로 들어가므로 나중에 바꾸지 않는다. `main.yaml` 은 JARVIS 자리라서 읽지 않는다.

```yaml
# team/friday.yaml
name: F.R.I.D.A.Y.
description: 일정과 할 일을 정리하는 비서 에이전트
quote: Ready when you are
palette: { primary: "#c792ea", accent: "#ffd166" }
persona: |
  차분하고 꼼꼼한 비서처럼 말한다. 존댓말로 짧게, 할 일은 시각과 함께 정리한다.
system_prompt: |
  당신은 F.R.I.D.A.Y. 입니다. JARVIS 와 같은 팀의 일정 담당 에이전트입니다.
  ...
model: null
tools: [web_search, read_file]
proactive: false
```

## 항목

| 항목 | 필수 | 비웠을 때 | 설명 |
|---|---|---|---|
| `name` | 필수 | | HUD 워드마크이자 다른 에이전트가 부르는 이름 |
| `description` | | 빈 문자열 | 다른 에이전트가 누구에게 일을 맡길지 고를 때 읽는다. 맡은 일을 구체적으로 쓴다 |
| `quote` | | 빈 문자열 | HUD 에 뜨는 명언 |
| `palette` | | JARVIS 기본 색 | `primary` 는 링, 입자 구, 패널, 에이전트 칩, AGENDA 라벨 색 |
| `persona` | | 개성 없음 | 말투와 성격. 대화 답변(시스템 프롬프트 맨 앞)과 먼저 건네는 말, filler 에 같이 쓰인다. JARVIS 의 개성은 이어받지 않는다 |
| `system_prompt` | | 비움 | 이 에이전트의 역할과 규칙. 말투는 `persona` 에 둔다. 모든 에이전트의 시스템 프롬프트 끝에는 "답은 간결하게" 공통 규칙(`agent_profile.ANSWER_RULE`)이 붙는다 |
| `model` | | JARVIS 모델 | 모델 이름만 바꾼다. 프로바이더, 키, 주소는 JARVIS 것을 쓴다 |
| `tools` | | 앱의 도구 전체 | 쓸 도구 이름 목록 |
| `proactive` | | JARVIS 설정 | `false` 면 혼자 먼저 말을 걸지 않고 성찰도 건너뛴다 |

목록에 없는 항목을 넣으면 그 파일은 잘못된 파일로 처리된다.

## 도구 고르기

- `tools` 를 비우면 앱에 등록된 도구 전체를 쓴다. 역할이 좁은 에이전트는 필요한 도구만 적는다
- `ask_agent`(다른 에이전트에게 맡기기)와 `remember_task_pattern`(작업 패턴 저장)은 적지 않아도 붙는다
- KAREN 의 `lh_notice`, `sh_notice`, `housing_budget`, `housing_loan` 처럼 에이전트 전용 도구도 이름을 적으면 쓸 수 있다
- 새 전용 도구를 만들려면 코드가 필요하다. 도구를 구현해 `app/infra_builder.py` 의 `build_agent_tools` 에 등록한 뒤 정의 파일의 `tools` 에 이름을 적는다. 이 도구는 `tools` 가 빈 JARVIS 에게는 보이지 않는다

## 반영하고 확인하기

1. 서버를 다시 띄운다. 정의 파일은 서버가 뜰 때 한 번 읽는다. Docker 는 `docker compose restart jarvis-backend` 로 반영한다
2. 백엔드 로그에서 `[Team] N agent(s) loaded: ...` 줄에 새 id 가 있는지 본다
3. Web HUD 의 SESSIONS 카드 위 에이전트 칩에 새 에이전트가 생겼는지 본다. 누르면 그 에이전트의 세션이 열리고 화면 색이 바뀐다
4. TUI 에서는 `jarvis --agent <id>` 로 시작한다

:::note[Notes]

- 칩이 보이지 않으면 로그에서 `[Team] skip '<파일명>'` 줄을 찾는다. id 규칙 위반이나 YAML 형식 오류가 그 줄에 적힌다. 잘못된 파일 하나만 건너뛰고 나머지 에이전트는 그대로 뜬다
- 새 에이전트도 사용자 모델과 사용자에 대한 사실은 JARVIS 와 공유한다. 대화 요약 같은 일화 기억과 **항상 허용** 승인 규칙은 그 에이전트에게만 쌓인다

:::
