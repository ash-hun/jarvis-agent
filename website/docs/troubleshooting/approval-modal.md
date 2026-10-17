---
sidebar_position: 5
title: 승인 모달
---

# 승인 모달

- 같은 세션을 여러 탭에서 열었으면 모든 탭이 모달을 받고, 한 탭이 답하면 나머지 모달은 닫힌다
- 120초 안에 답이 없으면 시간 초과로 거부된다. 응답이 "승인 요청에 시간 안에 답이 없어 … 실행을 멈췄습니다" 이고 ACTIVITY 에 `시간 초과로 거부` 가 남으면 이 경우다. 음성으로 답했는데 이렇게 나오면 그 말이 인식되지 않은 것이다. 같은 요청을 다시 하면 승인을 다시 묻는다. 자세한 흐름은 [Tool & Approve System](../concepts/conversation/tools-and-approval.md) 에 있다
- `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다
