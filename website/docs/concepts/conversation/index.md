---
sidebar_position: 0
title: Conversation
---

# Conversation

JARVIS 의 기본 기능인 Conversation 을 소개한다. 사용자와 대화하면서 속으로 생각하고(Inner Thought), 위험한 작업은 먼저 묻고(Tool & Approve System), 할 말이 있으면 먼저 말을 건다(Proactive Dialogue). 실행 방법은 [Quick Start](../../start/install.md)를 참고한다.

## 서비스 기능

### 풀려는 문제

대화형 비서는 묻는 말에만 답하고, 위험한 명령도 그대로 실행하고, 사용자가 잊은 일을 대신 챙기지 않는다. JARVIS 의 Conversation 은 이 세 가지를 한 대화 안에서 함께 다룬다.

### 무엇을 하나

| 기능 | 사용자가 보는 동작 |
|---|---|
| [Inner Thought](../architecture/inner-thought.md) | Conversation log 에 💭 표기가 보이면 Inner Thought 가 켜진 것이다 |
| [Tool & Approve System](./tools-and-approval.md) | "지금 폴더에 무슨 파일이 있어?" 처럼 도구가 필요한 요청에서, 승인이 필요하면 먼저 묻는다. Claude Code 의 AskUserQuestion 승인 체계와 같다 |
| [Proactive Dialogue](../architecture/proactive.md) | 사용자 입력이 없을 때도 백그라운드에서 돌다가, 알릴 일이 있으면 먼저 말한다. 알릴 필요가 없으면 아무것도 하지 않고, 이것이 자연스러운 동작이다 |
| [Sessions](./sessions.md) | 대화를 저장하고, 갈라 보고, 내보내고, 지운다 |
| [Open Loop](./open-loop.md) | 대화에서 흘린 약속을 AGENDA 카드에 남기고 닫는다 |
| [MCP Events](./mcp.md) | 캘린더나 메일 같은 소스의 새 항목을 묻기 전에 먼저 알린다 |
| [Scheduling](./scheduling.md) | 정한 시각에 알림이나 작업을 돌리고, 화면 앞에 없어도 결과를 전한다 |
| [Goals](./goals.md) | 한 번 맡긴 일을 대화가 없는 동안에도 차례마다 진행한다 |
| [Voice Interface](./voice.md) | 말로 묻고 소리로 듣는다 |

승인 창에서 고를 수 있는 답은 셋이다.

- `ALLOW`: 이번 한 번만 허용한다. Enter 도 같다
- `ALWAYS`: 서버가 제안한 명령 패턴을 기억해 두고 다음부터는 묻지 않는다. 서버가 패턴을 제안했을 때만 보인다
- `DENY`: 실행하지 않는다

승인 여부는 120초 안에 답해야 한다. 그렇지 않으면 자동으로 Deny 처리된다. 승인 규칙이 어떻게 쌓이고 에이전트마다 어떻게 나뉘는지는 [Tool & Approve System](./tools-and-approval.md)에서 다룬다.

:::danger
`ALWAYS` 를 누르면 패턴이 지금 세션 에이전트의 승인 규칙 파일(`~/.jarvis/approvals/<agent_id>.yaml`)에 저장된다. 지우거나 덮어쓰는 명령에 누르면 그 뒤로는 묻지 않고 실행한다. 되돌리려면 그 파일에서 해당 줄을 지운다.
:::

### 핵심 결과

- 승인을 거부하면 두 모델(gpt-4o-mini, gemma4:e4b) 모두 정해진 거부 문구로 턴을 끝내고, 재요청 때 다시 물었다(3번 중 3번)
- 음성 승인 답 분류에서 세 모델 모두 위험한 허용이 0 이었다
- 같은 약속 판정은 bge-m3 에서 정확도 0.83, 잘못 합침 0 이었다

## 세부 구현

### 하위 페이지

| 페이지 | 다루는 것 |
|---|---|
| [Sessions](./sessions.md) | 저장소(JSONL, Postgres), 한 세션에 한 요청, 분기, 삭제, 서브 에이전트 세션, 시험 세션 |
| [Tool & Approve System](./tools-and-approval.md) | 내장 도구, 도구 호출 한 번의 검사 순서, 승인 기억, 절차 학습, 스킬과 플러그인, 보안 파이프라인 |
| [Open Loop](./open-loop.md) | 약속 판정(근거, 같은 약속), 자동 닫힘, 임베딩 설정 |
| [MCP Events](./mcp.md) | MCP 도구를 주기적으로 불러 새 항목을 성찰의 재료로 넣는 방식 |
| [Scheduling](./scheduling.md) | `/schedule` 해석, 작업 종류, 결과 전달 |
| [Goals](./goals.md) | 목표의 한 차례, 사람 없는 차례의 경계 |
| [Voice Interface](./voice.md) | STT, TTS, 영어 음성, Full-voice, 음성 승인 |

### 공통 구조

한 요청은 세션 하나 안에서 처리된다. 세션은 에이전트 하나의 대화 한 줄기이고, 요청을 하나씩 받는다. 요청이 오면 응답과 함께 Inner Thought(Thought Router 가 건너뛸 수 있다)와 AGENDA 판단이 돌고, 에이전트 루프가 도구를 부를 때마다 승인 검사를 지난다. 사람 없이 도는 차례(목표, 스케줄 작업)는 승인 대신 에이전트 정의의 경계를 따른다.

### 다음에 읽을 것

- 이 절의 다른 문서: [Sessions](./sessions.md), [Open Loop](./open-loop.md), [MCP Events](./mcp.md), [Scheduling](./scheduling.md), [Goals](./goals.md), [Voice Interface](./voice.md)
- [Proactive Dialogue](../architecture/proactive.md): 🔔 를 언제 보내고 언제 참는지
- [Web HUD 사용가이드](../../start/web-hud.md): 카드, 입력, 세션 다루기
- [전체 용어집](../../reference/glossary.md): 이 문서에 나오는 이름들

## 성능 비교실험

하위 페이지 실험의 핵심 숫자다. 설정과 한계는 각 페이지의 성능 비교실험 절에 있다.

| 페이지 | 실험 | 핵심 숫자 |
|---|---|---|
| [Tool & Approve System](./tools-and-approval.md) | 거부 뒤 승인 흐름 준수 | 규칙과 루프 종료를 함께 넣자 gpt-4o-mini, gemma4:e4b 모두 세 단계 3/3. 프롬프트 규칙만이면 거부 직후 문구 0/2 |
| [Tool & Approve System](./tools-and-approval.md) | 음성 승인 답 분류 | 위험한 허용 세 모델 모두 0. 결정 정확도 e4b 1.0, e2b 0.917, gpt-4o-mini 0.75 |
| [Open Loop](./open-loop.md) | 임베딩 모델별 같은 약속 가르기 | bge-m3 정확도 0.83, 잘못 합침 0. nomic-embed-text 0.61, 다섯 쌍 합침 |
| [Goals](./goals.md) | 저장소 | 목표 1,000개에서 맡기기 중앙값 0.14ms, 두 번 맡겨도 1,000개 |
| [Goals](./goals.md) | KAREN 목표 한 차례 | 한 차례 25~29초, 하루(13차례) 약 0.39달러(gpt-4o 기준) |
| [Voice Interface](./voice.md) | Piper 영어 음성 합성 속도 | 합성 시간은 음성 길이의 0.19~0.22배 |
| [Sessions](./sessions.md) | 삭제와 다시 열기가 겹칠 때 | 세션별 잠금 전 2,000번 중 18.1% 가 기록 없이 세션만 남음, 잠금 뒤 0% |
| [Scheduling](./scheduling.md) | 알림이 실패할 때 놓친 공고 | 알림 실패율 30% 에서 놓친 공고 29.4% 가 0% 로, 두 번 알림 0건 |
| [MCP Events](./mcp.md) | 외부 이벤트를 끝내 전하지 못한 비율 | 사고 실패율 50% 에서 주기마다 5건일 때 48.3% 가 0% 로 |
| [Voice Interface](./voice.md) | JARVIS 답의 첫 소리까지 | 조각마다 합성하면 첫 소리 1.2~2.2초, 한 번에 합성하면 2.6~7.8초 |

