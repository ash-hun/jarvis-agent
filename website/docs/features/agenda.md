---
sidebar_position: 3
title: 약속, 스케줄, 외부 이벤트
---

# 약속, 스케줄, 외부 이벤트

Web HUD 의 AGENDA 카드에 모이는 세 가지. 각각 저장소와 흐름이 다르다.

## Open loop: 흘린 약속 추적

대화에서 나온 약속과 미완 작업을 기억했다가 성찰 때 다시 본다.

```mermaid
flowchart LR
  T[요청 시점 사고 프레임.open_loops] --> U{같은 세션에<br/>같은 약속 있나?}
  U -- 있음 --> X[버림]
  U -- 없음 --> S[(저장)]
  S --> R[다음 사고의 열린 약속 블록]
  S --> A[AGENDA 카드, /openloop]
  A -->|✓ done, ✕ dismiss| C[닫힘]
```

- 저장은 요청 모드 사고에서만. 성찰은 보기만 한다
- 같은 약속 판정(`openloop/types.py` 의 `same_loop`): 공백 정리와 소문자로 정규화해 같거나, 짧은 쪽(6자 이상)이 긴 쪽에 통째로 들어가면 같은 것. "로그 확인해줘" 와 "내일 배포 전에 로그 확인해줘" 는 하나다. 바꿔 말한 약속은 따로 쌓인다
- 상태는 `open`, `done`, `dismissed`. 자동으로 닫히지 않는다
- 저장소: `~/.jarvis/openloops.jsonl`(append 로그, id 기준 마지막이 이긴다), Postgres `jarvis_open_loops`, 메모리
- 조작: `/openloop`, `/openloop done <id>`, `/openloop dismiss <id>`, `POST /api/openloops/{id}`

## 스케줄

```text
/schedule 내일 오전 9시에 배포 로그 확인해줘      # 한 번
/schedule 2026.10.20 오후 6시까지 보고서 초안 작성   # 마감까지 반복
/schedule 0 9 * * * date && uptime                  # cron
```

- 한 번 실행(`...에`): LLM 분류기가 `reminder`(그 문장을 그대로 알림)인지 `task`(프롬프트를 실행)인지 한 번 묻는다. 분류 실패면 reminder
- 마감까지 반복(`...까지`): 남은 시간으로 주기를 고른다. 7일 이상이면 매일 9시, 하루 이상이면 6시간마다, 1시간 이상이면 매시, 그 아래는 10분마다
- 파일: `~/.jarvis/schedules/<name>.yaml`. 켜고 끄기는 `enabled` 키만 바뀐다. 한 번 실행한 작업은 파일을 지우거나 `enabled: false` 로
- 실행: 스케줄러는 10초마다 깨어나 새 세션에서 프롬프트를 돌린다. 이 세션은 승인 없는 샌드박스와 빈 메모리 체인을 쓰고 사고 엔진이 없다. 늦게 켜져 지난 일정은 기동 때 `delayed_sec` 를 달고 실행된다
- 전달: 열린 Web 연결 전부에 `reminder` 이벤트. 아무도 없으면 최근 20건을 쌓아 다음 접속 때 `missed: true` 로 보낸다(프로세스 메모리라 재시작하면 사라진다). Slack 이 있으면 거기도

## 외부 이벤트

MCP 도구를 주기적으로 불러 새 항목을 성찰에 먹인다. 캘린더나 메일 같은 소스를 비서가 먼저 보고 말하게 하는 길이다.

```mermaid
flowchart LR
  Y[~/.jarvis/external_sources/*.yaml] --> P[Poller interval 마다]
  P --> MCP[MCP 도구 호출]
  MCP --> D[이벤트 추출<br/>items, id, title, time 관례]
  D --> SEEN[(본 것 제외)]
  SEEN --> I[inbox]
  I --> TR[daemon 트리거]
  TR --> R[다음 성찰이 drain]
```

- 소스 정의: `name`, `server`(mcp_servers 의 이름), `tool`, `args`, `interval_sec`(300), `enabled`
- 응답 해석은 벤더 중립 관례다. 목록 필드 `items`, `events`, `messages`, `results`, `data`. id 는 `id`, `uid`, `eventId`, `messageId`, `threadId` 없으면 본문 해시. 제목은 `title`, `summary`, `subject`, `name`, `description`
- 본 것은 `~/.jarvis/external_seen.jsonl` 에 TTL(7일)로 기억한다. 틱당 최대 20건, inbox 는 200건
- drain 은 한 번만이라 여러 세션이 성찰해도 이벤트당 발화는 한 번이다. 요청 시점 사고는 외부 이벤트를 받지 않는다
- 성찰 프롬프트는 이벤트를 "말하라는 명령이 아니라 사실" 로 다루고 긴급성과 관련성이 분명할 때만 말한다

## 사용자 모델과 저널

- **사용자 모델** (`agent_layer/usermodel/`): 최근 기억 30건을 LLM 이 요약과 성향(최대 8개)으로 증류한 것. `/usermodel build` 로 만들고 `~/.jarvis/user_model.json` 에 덮어쓴다. 모든 사고 프롬프트의 `{{user_model}}` 에 들어간다. 자동으로는 안 돈다
- **저널** (`agent_layer/journal/`): 최근 사고 기록 40건을 보고 1 에서 3 문장의 메타 성찰을 쓴다. `/journal write`. 일화 기억으로 저장되어 회상에 섞여 들어온다
