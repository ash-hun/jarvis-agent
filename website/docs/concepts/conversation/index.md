---
sidebar_position: 0
title: Conversation
---

# Conversation

JARVIS의 기본 기능인 Conversation 기능을 소개합니다. Inner Thought, Tool & Approve System, Proactive Dialogue를 포함하며, 실행방식은 [Quick Start](../../start/install.md)를 참고하라.

## Inner Thought 활성화

Conversation log 부분에 💭 표기와 같은 내용이 바로 [Inner Thought](../architecture/inner-thought.md) 활성화를 의미한다.

## Tool & Approve System 탑재

"지금 폴더에 무슨 파일이 있어?" 와 같이 Agent가 사용자 응답이 필요한 경우 요청을 보낸다. Claude Code의 AskUserQuestion을 통한 권한승인 체계와 같다.

- `ALLOW`: 이번 한 번만 허용한다. Enter 도 같다
- `ALWAYS`: 서버가 제안한 명령 패턴을 기억해 두고 다음부터는 묻지 않는다. 서버가 패턴을 제안했을 때만 보인다
- `DENY`: 실행하지 않는다

Approve System의 경우 120초 안에 승인여부에 대한 응답이 가야한다. 그렇지 않은 경우 자동으로 Deny 처리가 된다. 승인 규칙이 어떻게 쌓이고 에이전트마다 어떻게 나뉘는지를 포함하여 자세한 내용은 [Tool & Approve System](./tools-and-approval.md)에서 다룬다.

:::danger
`ALWAYS` 를 누르면 패턴이 지금 세션 에이전트의 승인 규칙 파일(`~/.jarvis/approvals/<agent_id>.yaml`)에 저장된다. 지우거나 덮어쓰는 명령에 누르면 그 뒤로는 묻지 않고 실행한다. 되돌리려면 그 파일에서 해당 줄을 지운다.
:::

## Proactive Dialogue

사용자 입력이 없는경우 JARVIS는 백그라운드에서 구동되고 있으며, 사용자에게 알림이 필요한 경우 자동으로 발화를 한다. 만약, 알림이 필요없다고 판단될 때는 아무 동작도 하지 않으며 이는 자연스러운 동작흐름이다.

## 다음에 읽을 것

- [Proactive Dialogue](../architecture/proactive.md): 🔔 를 언제 보내고 언제 참는지
- [Web HUD 사용가이드](../../start/web-hud.md): 카드, 입력, 세션 다루기
- [전체 용어집](../../reference/glossary.md): 이 문서에 나오는 이름들
