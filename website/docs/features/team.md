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
