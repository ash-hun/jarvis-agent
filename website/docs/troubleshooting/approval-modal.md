---
sidebar_position: 5
title: 승인 모달
---

# 승인 모달

- 같은 세션을 여러 탭에서 열었으면 모든 탭이 모달을 받고, 한 탭이 답하면 나머지 모달은 닫힌다
- 120초 안에 답이 없으면 거부로 처리되고, 도구 결과에 `denied` 가 온다
- `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다
