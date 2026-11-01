---
sidebar_position: 0
title: Conversation
---

import InfoConversation from '@site/src/figures/info-conversation.svg';

# Conversation

Jarvis-Agent의 가장 기본이 되는 기능인 Conversation을 소개한다. 단순하게 사용자의 request에 agent가 response하는 것이 아닌 사용자와 대화하면서 속으로 생각하고(Inner Thought), 리스크 있는 작업은 허가를 받으며(Tool & Approve System), 사용자에게 해야할 말이 있으면 먼저 말을 거는(Proactive Dialogue) 전체 communication layer이다. 실행 방법은 [Quick Start](../../start/install.md)를 참고한다.

<figure className="info-fig">
  <InfoConversation />
</figure>

## 개요

기존의 대화형 Assistant는 묻는 말에만 답하고, 위험한 명령도 별다른 확인 없이 그대로 실행하며, 사용자가 잊은 일을 대신 챙기지 않는다. 이를 보완하려고 별도의 할 일 앱이나 권한 설정 화면을 덧붙이기도 하지만, 대화 바깥에 따로 떨어진 기능은 결국 사용자가 직접 챙겨야 하는 일이 하나 더 늘어날 뿐이다. Jarvis-Agent의 Conversation은 이러한 부분에서 착안하여 기본적으로 아래 과정을 가지며, 상황에 따라 적절히 조율하여 수행되게 한다.

> Inner Thought - PreResponse / PostResponse - Permission Check  

### 공통 구조

1개의 요청은 1개의 Session 안에서 처리된다. Session은 에이전트 하나의 최소 소통단위이다. 사용자의 요청이 에이전트에게 들어오면 응답과 함께 Inner Thought(단, Thought Router 가 건너뛸 수 있다)와 AGENDA 판단이 결정되고, 에이전트 루프가 도구를 부를 때마다 승인 검사를 지난다. 사람 없이 도는 차례(목표, 스케줄 작업)는 승인 대신 에이전트 정의의 경계를 따른다.

### 기능 목록

| 페이지 | 다루는 것 |
|---|---|
| [Inner Thought](./inner-thought.md) | Conversation log 에 💭 표기가 보이면 Inner Thought 가 켜진 것이다 |
| [Sessions](./sessions.md) | 저장소(JSONL, Postgres), 한 세션에 한 요청, 분기, 삭제, 서브 에이전트 세션, 시험 세션 |
| [Proactive Dialogue](./proactive.md) | 사용자 입력이 없을 때도 백그라운드에서 돌다가, 알릴 일이 있으면 먼저 말한다. 알릴 필요가 없으면 아무것도 하지 않고, 이것이 자연스러운 동작이다 |
| [Tool & Approve System](./tools-and-approval.md) | 내장 도구, 도구 호출 한 번의 검사 순서, 승인 기억, 절차 학습, 스킬과 플러그인, 보안 파이프라인 |
| [Open Loop](./open-loop.md) | 약속 판정(근거, 같은 약속), 자동 닫힘, 임베딩 설정 |
| [MCP Events](./mcp.md) | MCP 도구를 주기적으로 불러 새 항목을 성찰의 재료로 넣는 방식 |
| [Scheduling](./scheduling.md) | `/schedule` 을 이용해 정한 시각에 알림이나 작업을 돌리고, 화면 앞에 없어도 결과를 전한다. |
| [Goals](./goals.md) | 한 번 맡긴 일을 대화가 없는 동안에도 차례마다 진행한다 |
| [Voice Interface](./voice.md) | STT, TTS, 영어 음성, Full-voice, 음성 승인 |

