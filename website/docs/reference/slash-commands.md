---
sidebar_position: 2
title: 공용 커맨드
---

# 공용 커맨드

슬래시 커맨드는 LLM 을 거치지 않고 서버가 바로 처리하는 명령이다.

`/명령` 이 입력의 어디에 있든 서버의 디스패처가 먼저 가로챈다. 명령이 입력을 다 소비하면 LLM 으로 보내지 않고, 남은 글이 있으면 그 글만 LLM 으로 보낸다. Web HUD 에서는 `/` 를 치면 자동완성 팝업이 뜬다.

| 커맨드 | 별칭 | 설명 |
|---|---|---|
| `/help` | `/?` | 사용 가능한 명령 목록 |
| `/test` | `/t`, `/pytest` | 유닛 테스트 실행과 결과 리포트 |
| `/schedule` | | `<시각>에 <내용>` 한 번, `<날짜 시각>까지 <내용>` 마감까지 반복, cron 식 |
| `/remember` | | `<text>` 로 사실 저장. `list`, `search <키워드>`, `forget <id>`, `conflicts`, `reembed` |
| `/patterns` | | 지금 에이전트의 작업 패턴(사용자가 알려 준 방식) 목록. `forget <이름>` 으로 지운다 |
| `/sessions` | | 저장된 세션 목록 |
| `/branch` | | `[session_id]` 세션을 특정 시점에서 분기 |
| `/tools` | | 현재 사용 가능한 도구 목록 |
| `/procedures` | | 학습된 절차 (`approve <name>`, `reject <name>`, `show <name>`, `learn [session_id]`) |
| `/compact` | | 현재 세션을 요약해 장기 기억에 저장 |
| `/export` | | 현재 세션 대화를 파일로 (`md`, `json`, `~/.jarvis/exports/`) |
| `/cost` | | 현재 세션 토큰 사용량과 추정 비용, 모델별 집계 |
| `/openloop` | | 추적 중인 약속과 미완 작업 (`done <id>`, `dismiss <id>`) |
| `/usermodel` | | 증류된 사용자 모델 표시, `build` 로 갱신 |
| `/journal` | | 자기 성찰 저널 표시, `write` 로 작성 |
| `/orchestrate` | | 멀티 에이전트 호출 (`<pattern> <task>`, `list`) |
| `/cleanup` | | 옛 서브 에이전트 세션과 옛 STM 테이블 보기. `agents confirm`, `stm confirm` 으로 삭제 |
| `/exit` | | TUI 종료 |
| `/<절차 이름>` | | 승인된 절차 하나가 스킬 하나다 |

사용 예는 다음과 같다.

```text
/schedule 내일 오전 9시에 날씨 알려줘
/schedule 30분 뒤에 배포 로그 확인
/schedule 2026.10.20 오후 6시까지 보고서 초안 작성
/schedule 0 9 * * * date && uptime
/test -k "test_policy"
/orchestrate hierarchical 분기 보고서 작성
/orchestrate blackboard --agents a,b --promote 시장 분석
```

직접 만든 스킬은 `~/.jarvis/skills/` 에 Markdown 으로 둔다. 파일 형식은 [확장하기](../concepts/extending.md) 에 있다.

`/openloop`, `/usermodel`, `/journal` 은 내적 사고가 켜져 있을 때만 등록된다. `/orchestrate` 는 에이전트 정의가 하나 이상 있을 때만 등록된다.
