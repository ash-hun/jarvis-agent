---
sidebar_position: 10
title: 음성
---

# 음성

구체를 눌러도 음성 입력이 되지 않거나, 서버 STT, TTS 가 동작하지 않는다.

## 원인과 해결

- 브라우저 STT 가 안 됨: 브라우저 STT 는 Chrome 계열에서 동작한다. 지원하지 않는 브라우저에서는 구체를 클릭했을 때 SYS 에러가 한 줄 뜬다
- 서버 STT, TTS 가 안 됨: `uv sync --extra voice` 로 설치해야 한다. Docker 의 `web` 백엔드 이미지에는 이미 들어 있다
- 데스크톱 앱에서 브라우저 STT 가 `network` 오류로 끊김: Electron 은 Web Speech API 를 쓰지 못한다. `JARVIS_VOICE__STT_FALLBACK=whisper`(기본값)면 HUD 가 녹음해 서버의 whisper 로 받아 적으므로 `voice` extra 가 있어야 한다. 모델은 처음 쓸 때 읽는다

관련 문서: [Voice Interface](../concepts/conversation/voice.md)
