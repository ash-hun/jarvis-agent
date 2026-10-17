---
sidebar_position: 5
title: 승인 모달
---

# 승인 모달

- 같은 세션을 여러 탭에서 열었으면 모든 탭이 모달을 받고, 한 탭이 답하면 나머지 모달은 닫힌다
- 120초 안에 답이 없으면 거부로 처리되고, 도구 결과에 `denied` 가 온다. 응답은 "승인을 받지 못해 … 실행을 멈췄습니다" 한 줄이다. 같은 요청을 다시 하면 승인을 다시 묻는다
- `ALWAYS` 로 남긴 규칙은 `~/.jarvis/approvals/<agent_id>.yaml`(JARVIS 는 `main.yaml`)에 있다. 잘못 남겼으면 그 줄을 지운다. 모든 에이전트에 적용할 규칙은 공용 `~/.jarvis/approvals.yaml` 에 손으로 적는다
