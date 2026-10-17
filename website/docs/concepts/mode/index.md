---
sidebar_position: 0
title: Mode
---

# Mode

Web HUD 는 두 축의 모드를 따로 고른다. 하나는 말로 주고받는 방식이고, 다른 하나는 화면과 에이전트가 무엇에 집중하는지다. 두 축은 겹쳐 쓸 수 있어서, Full-voice 로 Focus 작업을 해도 된다.

| 축 | 모드 | 켜는 법 | 무엇이 바뀌나 |
|---|---|---|---|
| 음성 | Default | 헤더 `DEFAULT` | 응답은 화면으로 본다. 구체를 눌러 말한 요청만 읽어 준다 |
| 음성 | Full-voice | 헤더 `FULL-VOICE` | 응답, 승인 요청, 먼저 건네는 말을 읽고 답을 듣는다. 자세한 동작은 [Voice Interface](../conversation/voice.md#full-voice) |
| 작업 | Focus | `/focus <작업>`, 음성 `포커스 모드 <작업>` | 작업 하나에 sub-agent 넷을 붙이고 화면을 네 영역으로 바꾼다. [Focus Mode](./focus-mode.md) |

## 같이 쓸 때

- Focus 중에도 음성 모드는 헤더에서 그대로 바꾼다. 헤더의 `FOCUS` 표시는 음성 모드와 따로 붙는다
- 음성으로 시작한 요청이면 Default 에서도 승인을 음성으로 묻는다. Focus 중이어도 같다
- Focus 를 끝내도 음성 모드는 바뀌지 않는다
