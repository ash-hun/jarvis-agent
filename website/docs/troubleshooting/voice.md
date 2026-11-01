---
sidebar_position: 10
title: 음성
---

# 음성

구체를 눌러도 음성 입력이 되지 않거나, 서버 STT, TTS 나 TUI 음성이 동작하지 않는다.

## 원인과 해결

- 브라우저 STT 가 안 됨: 브라우저 STT 는 Chrome 계열에서 동작한다. 지원하지 않는 브라우저에서는 구체를 클릭했을 때 SYS 에러가 한 줄 뜬다
- 서버 STT, TTS 가 안 됨: `uv sync --extra voice` 로 설치해야 한다. Docker 의 `web` 백엔드 이미지에는 이미 들어 있다
- TUI 음성이 안 됨: 시스템 오디오 도구(재생은 afplay, paplay, aplay, ffplay 중 하나, 녹음은 sox 나 arecord)도 있어야 한다

관련 문서: [Voice Interface](../concepts/conversation/voice.md)
