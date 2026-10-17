---
sidebar_position: 1
title: 먼저 건네는 말이 오지 않을 때
---

# 먼저 건네는 말이 오지 않을 때

JARVIS 는 침묵할 때마다 그 이유를 백엔드 로그에 남긴다. 아래 중 어느 것인지 먼저 확인한다.

```text
[Thought] proactive silent: cooldown
[Thought] proactive silent: confidence 0.72 < 0.85
[Thought] proactive silent: empty utterance
[Thought] proactive silent: decision=silent
```

- `cooldown`: 마지막 발화 뒤 300초가 지나지 않았다
- `confidence`: 사고 프레임의 확신도가 임계치보다 낮다. 피드백 학습으로 임계치가 올라갔을 수도 있다
- `empty utterance`: 모델이 건넬 말을 채우지 않았다. 사고 템플릿에 `utterance` 키가 있는지 확인한다
- `[Proactive] suppressed during turn hook`: 그 세션이 Focus 작업 중이다. Focus 동안에는 🔔 를 보내지 않는다(💬 filler 와 맡긴 일의 답은 보낸다). `/focus stop` 으로 끝내면 다시 나온다
- 로그가 아예 없으면 daemon 이 꺼져 있거나(`JARVIS_PROACTIVE__DAEMON_ENABLED`) 성찰 프레임이 깨지고 있는 것이다
