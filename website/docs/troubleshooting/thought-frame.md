---
sidebar_position: 2
title: 사고 프레임이 깨진다
---

# 사고 프레임이 깨진다

💭 가 뜨지 않거나 먼저 건네는 말이 끝내 오지 않고, 백엔드 로그에 사고 프레임 오류가 찍힌다. 사고 모델이 JSON 스키마를 지키지 못한 경우다.

## 확인 순서

1. 백엔드 로그에서 `[Thought]` 로 시작하는 프레임 오류를 찾는다.

   ```text
   [Thought] reflection frame unparsable (len=1269): ...
   [Thought] frame invalid: decision: Input should be 'act', 'ask' or 'silent'
   [Thought] dropped invalid proactive_actions: ...
   ```

2. Ollama 를 쓴다면 `call failed ... 501` 이 찍히는지 본다.
3. 어떤 사고 모델을 쓰는지 `JARVIS_THOUGHT__MODEL` 을 확인한다. 비어 있으면 메인 모델이 사고도 맡는다.

## 원인과 해결

- `dropped invalid proactive_actions`: 행동 후보만 버리고 프레임은 살린 경우라서 괜찮다
- `reflection frame unparsable`, `frame invalid` 가 반복됨: 사고 모델이 스키마를 지키지 못한다. 사고 모델을 바꾼다. 검증한 모델은 [사고 모델 고르기](../reference/configuration.md#사고-모델-고르기)에 있다
- `call failed ... 501`: Ollama 는 스키마를 `format` 으로 강제하는데, 모델이 structured output 을 지원하지 않으면 이 줄이 찍히고 사고가 통째로 생략된다. structured output 을 지원하는 모델로 바꾼다

관련 문서: [Inner Thought → 사고 프레임](../concepts/conversation/inner-thought.md#사고-프레임)
