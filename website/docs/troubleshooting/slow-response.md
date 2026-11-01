---
sidebar_position: 3
title: 응답이 느리다
---

# 응답이 느리다

메시지를 보낸 뒤 첫 글자가 늦게 나오거나, 성찰이 도는 동안 요청이 기다린다. 대개 사고와 메인 응답이 같은 자원을 나눠 쓰는 데서 온다.

## 확인 순서

1. 사고 모델과 메인 모델이 같은 GPU 나 같은 Ollama 에서 도는지 본다(`JARVIS_THOUGHT__MODEL`, `JARVIS_THOUGHT__BASE_URL`).
2. `JARVIS_THOUGHT__REQUEST_TIMING` 값을 확인한다.
3. 요청이 없을 때도 느린지, 성찰이 도는 동안만 느린지 가른다.

## 원인과 해결

- 사고와 메인이 GPU 한 장을 나눠 씀: 로컬 GPU 한 장에서 사고와 메인을 같이 돌리면 서로 느려진다. `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 두면 응답이 먼저 나오고 사고는 뒤에 돈다
- 성찰 자체가 느림: `HISTORY_TURNS`, `HISTORY_CHARS` 를 줄이거나 사고 모델을 작은 것으로 바꾼다
- 호스트 Ollama 하나에서 성찰과 요청이 줄을 섬: Ollama 의 동시 처리 수를 늘린다. 명령은 [호스트 Ollama 팁](../reference/configuration.md#호스트-ollama-팁)에 있다
- 그래도 남는 지연: 메인 모델이 프롬프트(시스템 프롬프트, 도구 목록)를 처리하는 시간이다

관련 문서: [Inner Thought](../concepts/conversation/inner-thought.md), [요청 사고 시점](../reference/configuration.md#요청-사고-시점)
