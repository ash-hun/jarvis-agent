---
sidebar_position: 5
title: 승인 모달
---

# 승인 모달

승인 모달이 여러 탭에 한꺼번에 뜨거나, 답했는데 실행이 멈췄거나, `ALWAYS` 로 남긴 규칙을 되돌리고 싶을 때 본다.

## 확인 순서

1. Web HUD 의 ACTIVITY 에 `시간 초과로 거부` 나 "다른 창에서 처리됨" 이 남았는지 본다.
2. 응답이 "승인 요청에 시간 안에 답이 없어 … 실행을 멈췄습니다" 인지 본다.
3. 묻지 않고 실행되거나 막히는 명령이 있으면 그 에이전트의 규칙 파일 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)을 연다.

## 원인과 해결

- 모든 탭에 모달이 뜸: 같은 세션을 여러 탭에서 열었으면 모든 탭이 모달을 받는다. 한 탭이 답하면 나머지 모달은 닫힌다
- 시간 초과로 거부됨: 120초 안에 답이 없으면 시간 초과로 거부된다. 응답이 "승인 요청에 시간 안에 답이 없어 … 실행을 멈췄습니다" 이고 ACTIVITY 에 `시간 초과로 거부` 가 남으면 이 경우다. 음성으로 답했는데 이렇게 나오면 그 말이 인식되지 않은 것이다. 같은 요청을 다시 하면 승인을 다시 묻는다
- `ALWAYS` 규칙을 잘못 남김: `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다

관련 문서: [Tool & Approve System](../concepts/conversation/tools-and-approval.md), [승인 기억](../concepts/conversation/tools-and-approval.md#승인-기억)
