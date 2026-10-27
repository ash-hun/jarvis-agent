---
sidebar_position: 1
title: 먼저 건네는 말이 오지 않을 때
---

# 먼저 건네는 말이 오지 않을 때

JARVIS 는 먼저 말하지 않을 때마다 그 이유를 백엔드 로그에 남긴다. 아래 중 어느 것인지 먼저 확인한다.

```text
[Thought] proactive silent: cooldown
[Thought] proactive silent: confidence 0.72 < 0.85
[Thought] proactive silent: empty utterance
[Thought] proactive silent: decision=silent
[Thought] proactive silent: awaiting reply
[Thought] proactive silent: repeats a recent proactive message
[Thought] proactive silent: repeats the last answer
[Proactive] suppressed while answering: <문장>
```

- `decision=<값>`: 사고가 `act`, `ask` 가 아닌 결정(`silent` 등)을 냈다. 지금 말할 일이 없다고 판단한 것으로, 정상 동작이다
- `awaiting reply`: 직전 🔔 에 아직 답이 없다. 사용자가 메시지나 피드백을 보내면 다시 말할 수 있다. 600초 동안 답이 없으면 그 발화를 한 번 무시로 학습한다
- `cooldown`: 마지막 발화 뒤 300초가 지나지 않았다
- `confidence`: 사고 프레임의 확신도가 임계치보다 낮다. Process Pattern Analysis 로 임계치가 올라갔을 수도 있다
- `empty utterance`: 모델이 건넬 말을 채우지 않았다. 사고 템플릿에 `utterance` 키가 있는지 확인한다
- `repeats a recent proactive message`, `repeats the last answer`: 사고가 최근 🔔 나 10분 안에 한 답과 같은 내용을 다시 골랐다. 정상 동작이다
- `[Proactive] suppressed while answering`: 세션이 답하는 중에 🔔 가 생겼다. 답과 섞이지 않게 버린 것으로, 정상 동작이다
- `[Proactive] suppressed during turn hook`: 그 세션이 Focus 작업 중이다. Focus 동안에는 🔔 를 보내지 않는다(💬 filler 와 맡긴 일의 답은 보낸다). `/focus stop` 으로 끝내면 다시 나온다
- 로그가 아예 없으면 daemon 이 꺼져 있거나(`JARVIS_PROACTIVE__DAEMON_ENABLED`) 성찰 프레임이 깨지고 있는 것이다
