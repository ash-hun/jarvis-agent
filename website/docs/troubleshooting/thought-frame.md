---
sidebar_position: 2
title: 사고 프레임이 깨진다
---

# 사고 프레임이 깨진다

```text
[Thought] reflection frame unparsable (len=1269): ...
[Thought] frame invalid: decision: Input should be 'act', 'ask' or 'silent'
[Thought] dropped invalid proactive_actions: ...
```

사고 모델이 JSON 스키마를 지키지 못한 것이다. 마지막 줄은 행동 후보만 버리고 프레임은 살린 경우라서 괜찮다. 앞의 두 줄이 반복되면 사고 모델을 바꾼다. Ollama 는 스키마를 `format` 으로 강제하는데, 모델이 structured output 을 지원하지 않으면 `call failed ... 501` 이 찍히고 사고가 통째로 생략된다.
