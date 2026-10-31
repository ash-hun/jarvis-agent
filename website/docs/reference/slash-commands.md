---
sidebar_position: 2
title: 공용 커맨드
---

# 공용 커맨드

슬래시 커맨드는 LLM 을 거치지 않고 서버가 바로 처리하는 명령이다.

`/명령` 이 입력의 어디에 있든 서버의 디스패처가 먼저 가로챈다. 명령이 입력을 다 소비하면 LLM 으로 보내지 않고, 남은 글이 있으면 그 글만 LLM 으로 보낸다. Web HUD 에서는 `/` 를 치면 자동완성 팝업이 뜬다. 스킬(`/test`, 승인된 절차의 `/<이름>`)은 예외다. 디스패처가 가로채지 않고, 스킬 본문으로 펼친 프롬프트를 LLM 에 보낸다.

| 커맨드 | 별칭 | 설명 |
|---|---|---|
| `/help` | `/?` | 사용 가능한 명령 목록 |
| `/test` | `/t`, `/pytest`, `/ut` | 유닛 테스트 실행과 결과 리포트. 레포의 `skills/test.md` 스킬이라 `JARVIS_PLUGIN__SKILLS_DIR=./skills`(`.env.example` 값)일 때만 있다 |
| `/schedule` | | `<시각>에 <내용>` 한 번, `<YYYY.MM.DD 시각>까지 <내용>` 마감까지 반복. cron 식은 받지 않는다 |
| `/remember` | | `<text>` 로 사실 저장. `list`, `search <키워드>`, `forget <id>`, `conflicts`, `reembed` |
| `/patterns` | | 지금 에이전트의 작업 패턴(사용자가 알려 준 방식) 목록. `forget <이름>` 으로 지운다 |
| `/housing` | | 대출 자격용 주거 프로필(무주택, 생애최초, 혼인, 연소득, 순자산, 생년월일이나 나이, 관심 지역, 보유 현금, 월 여유자금) 보기. `set 연소득=6000만 현금=7000만 월여유자금=150만` 으로 준 항목만 고치고, `clear` 로 지운다 |
| `/goal` | | 지금 세션의 에이전트에게 [목표](../concepts/conversation/goals.md)를 맡긴다(`<문장>`). 인자 없으면 맡은 목표 목록, `stop <문장 일부>` 로 멈춘다. 같은 문장을 다시 맡겨도 하나다 |
| `/sessions` | | 저장된 세션 목록 |
| `/branch` | | `[session_id]` 세션을 특정 시점에서 분기 |
| `/tools` | | 현재 사용 가능한 도구 목록 |
| `/procedures` | | 학습된 절차 (`approve <name>`, `reject <name>`, `show <name>`, `learn [session_id]`) |
| `/compact` | | 명령을 친 세션을 요약해 장기 기억에 저장 |
| `/export` | | 현재 세션 대화를 파일로 (`md`, `json`, `~/.jarvis/exports/`) |
| `/cost` | | 현재 세션 토큰 사용량과 추정 비용, 모델별 집계 |
| `/openloop` | | 추적 중인 약속과 미완 작업 (`done <id>`, `dismiss <id>`) |
| `/usermodel` | | 증류된 사용자 모델 표시, `build` 로 갱신 |
| `/journal` | | 자기 성찰 저널 표시, `write` 로 작성 |
| `/orchestrate` | | 멀티 에이전트 호출 (`<pattern> <task>`, `list`) |
| `/focus` | | `<작업>` 으로 [Focus 모드](../concepts/mode/focus-mode.md) 시작, `stop` 으로 종료, 인자 없으면 현황. Web HUD 전용이고 디스패처보다 먼저 처리된다 |
| `/cleanup` | | 옛 서브 에이전트 세션, 옛 STM 테이블, 시험 흔적(시험 세션과 그 세션이 남긴 장기, 작업 기억) 보기. `agents confirm`, `stm confirm`, `tests confirm` 으로 삭제 |
| `/exit` | | TUI 종료 |
| `/<절차 이름>` | | 승인된 절차마다 스킬 명령이 하나씩 생긴다 |

사용 예는 다음과 같다.

```text
/schedule 내일 오전 9시에 날씨 알려줘
/schedule 30분 뒤에 배포 로그 확인
/schedule 2026.10.20 오후 6시까지 보고서 초안 작성
/goal 조건 및 가장 좋은 원리금 납부액을 추천하는 공고만 알려줘
/test -k "test_policy"
/orchestrate hierarchical 분기 보고서 작성
/orchestrate blackboard --agents a,b --promote 시장 분석
```

직접 만든 스킬은 `~/.jarvis/skills/` 에 Markdown 으로 둔다. 파일 형식은 [Extension](../concepts/extension.md) 에 있다.

`/openloop`, `/usermodel`, `/journal` 은 Inner Thought 가 켜져 있을 때만 등록되고, `/usermodel` 은 `JARVIS_USER_MODEL__ENABLED` 도 켜져 있어야 한다. `/goal` 은 스케줄러가 켜져 있을 때만, `/orchestrate` 는 `JARVIS_AGENTS__ENABLED` 가 켜져 있고 서브 에이전트 정의가 하나 이상 실렸을 때만 등록된다. `/exit` 는 TUI 입력창이 직접 처리하고, `/focus` 는 Web HUD 에만 있다.

cron 식으로 반복하는 작업은 `~/.jarvis/schedules/*.yaml`(`JARVIS_SCHEDULER__SCHEDULES_DIR`)에 `schedule: "0 9 * * *"` 로 적는다. 형식은 [Scheduling](../concepts/conversation/scheduling.md) 에 있다.
