---
sidebar_position: 9
title: 최상위 에이전트 팀
---

# 최상위 에이전트 팀

JARVIS 와 같은 층에 에이전트를 더 둔다. 첫 번째이자 전체를 총괄하는 에이전트가 JARVIS(id `main`)이고, 정보 수집을 맡는 KAREN(id `karen`)처럼 목적이 다른 에이전트를 파일 하나로 늘린다. 구현은 `app/agent_registry.py`.

[멀티 에이전트](./multi-agent.md)의 서브 에이전트와 다르다. 서브 에이전트는 부모 턴 안에서 잠깐 도는 도구이고, 최상위 에이전트는 자기 세션, 기억, 약속, 승인 규칙, 브랜드를 가진다.

## 정의 파일

`JARVIS_TEAM__DIR`(기본 `~/.jarvis/team`, docker 는 저장소의 `team/`)의 `<id>.yaml` 하나가 에이전트 하나다. 파일 이름이 id 이고, 비운 항목은 JARVIS 설정을 이어받는다.

```yaml
# team/karen.yaml
name: K.A.R.E.N.              # 워드마크이자 다른 에이전트가 부르는 이름
description: 정보 수집 담당      # 다른 에이전트가 누구에게 맡길지 고를 때 읽는다
quote: Eyes on everything
palette: { primary: "#f0607c", accent: "#ffd166" }
system_prompt: |
  당신은 K.A.R.E.N. 입니다 ...
model: null                   # 모델 이름만 바꾼다. 프로바이더와 키는 JARVIS 것
tools: [web_search, web_fetch, read_file]   # 비우면 전체
proactive: false              # 비우면 JARVIS 의 proactive 설정
```

- id 는 `^[a-z][a-z0-9_-]{0,31}$`. `main.yaml` 은 무시한다. JARVIS 는 env(`JARVIS_BRAND__*`, `JARVIS_LLM__*`)가 정본이다
- 잘못된 파일은 로그만 남기고 그 파일만 건너뛴다
- 사고 설정은 JARVIS 것을 같이 쓰고, proactive 피드백 학습기는 에이전트마다 따로 둔다

## 무엇을 공유하나

| 항목 | 규칙 |
|---|---|
| 사용자 모델 | 공유. 파일 하나를 모든 에이전트가 읽는다 |
| 장기 기억 | 사용자에 대한 사실(semantic)만 공유. 대화 요약, 사고 로그 같은 일화(episodic)는 쓴 에이전트 전용 |

장기 기억의 공유 여부는 쓰기 경로가 정한다(`memory_service.WRITE_RULES`). `/remember`, 사용자 모델 증류, 일화에서 뽑은 사실은 shared 로, 나머지는 private 로 쓴다. 기억 범위의 `agent_id` 는 세션의 에이전트 id 다.

범위를 도입하기 전의 옛 행은 Postgres 저장소가 열릴 때 main 행으로 채운다. 이때 사실만 shared 로, 일화는 main 전용으로 둔다. 예전 backfill 이 shared 로 둔 일화도 같은 때 private 로 고친다. 두 번 열어도 결과가 같다.

## 세션은 한 에이전트의 것

세션은 만들 때 에이전트가 정해지고 바뀌지 않는다(`jarvis_sessions.agent_id`, jsonl 은 `.meta.json` 의 `agent_id`). 에이전트가 정해지기 전에 만든 세션은 main 이다.

- Web: `POST /api/sessions {"agent": "karen"}`, `/ws?session_id=..&agent=karen`. 이미 있는 세션은 저장된 에이전트로 열리고 `agent` 는 무시한다. 모르는 에이전트는 400, ws 는 close `4404`
- TUI: `jarvis --agent karen` 은 `default-karen` 세션으로 시작한다. `--session ID` 는 그 세션을 만든 에이전트로 연다
- 분기는 부모와 같은 에이전트
- 스케줄: 작업 YAML 의 `agent: karen` 이면 그 에이전트의 모델, 시스템 프롬프트, 기억 범위로 돈다. `/schedule` 로 만든 작업은 명령을 친 세션의 에이전트가 들어간다
- 성찰 daemon 은 열린 세션 전부를 돈다. proactive 가 꺼진 에이전트(KAREN 기본값)의 세션은 성찰을 건너뛴다

## 승인 규칙은 두 겹

공용 `~/.jarvis/approvals.yaml` 은 모든 에이전트가 읽고 사람이 고친다. 승인 화면의 **항상 허용** 은 그 세션 에이전트의 `~/.jarvis/approvals/<id>.yaml` 에만 쌓인다(`LayeredApprovalRules`). 에이전트를 나누기 전 `approvals.yaml` 에 쌓인 규칙은 그대로 공용이 된다. 자세한 건 [도구와 승인](./tools-and-approval.md).

## AGENDA 는 모두의 것

AGENDA 카드는 모든 에이전트의 스케줄과 약속을 한 목록에 보여주고, 항목마다 에이전트 이름 라벨을 그 에이전트의 primary 색으로 단다. 약속(`OpenLoop.agent_id`)은 감지한 세션의 에이전트, 스케줄은 작업의 `agent` 다. 약속을 닫는 판정(사고의 closed_loops, 취소하는 말)은 그 약속을 만든 세션에서만 한다.
