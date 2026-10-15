---
sidebar_position: 3
title: 응답이 느리다
---

# 응답이 느리다

로컬 GPU 한 장에서 사고와 메인을 같이 돌리면 서로 느려진다. `JARVIS_THOUGHT__REQUEST_TIMING=after` 로 두면 응답이 먼저 나오고 사고는 뒤에 돈다. 성찰 자체가 느리면 `HISTORY_TURNS`, `HISTORY_CHARS` 를 줄이거나 사고 모델을 작은 것으로 바꾼다. 그래도 남는 지연은 메인 모델이 프롬프트(시스템 프롬프트, 도구 목록)를 처리하는 시간이다.
