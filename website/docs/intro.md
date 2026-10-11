---
sidebar_position: 1
slug: /
title: jarvis-agent 소개
---

# jarvis-agent

개인 AI 비서 에이전트. 터미널 TUI 와 브라우저 Web HUD 두 가지 화면으로 쓰며, 여러 LLM 프로바이더, 멀티 에이전트 오케스트레이션, 장기 메모리 위에 **요청에만 답하지 않고 스스로 사고하고 먼저 행동하는 proactive agent** 를 얹었다.

<div align="center">
  <img src="/jarvis-agent/img/hud-motion.gif" alt="Web HUD. 내적 사고, 마크다운 응답, 먼저 건네는 말, 승인 기억" />
</div>

## 무엇이 다른가

보통의 채팅 에이전트는 사용자가 말해야 움직인다. jarvis-agent 는 매 요청마다 메인 응답과 **분리된 사고 호출**(inner thought)로 구조화된 판단을 만들고, 그 판단으로 다음을 정한다.

- 지금 바로 답할지, "잠깐만요, 확인할게요" 를 먼저 말하고 뒤에서 처리할지
- 대화에서 흘린 약속과 미완 작업을 기억해 둘지(open loop)
- 요청이 없는 시간에 스스로 성찰해서 먼저 말을 걸지, 침묵할지
- 먼저 건넨 말이 도움이 됐는지 배우고 다음 발화 기준을 조정할지

그 위에 승인 기억(한 번 허용한 명령 패턴은 다시 묻지 않음), 절차 학습(여러 도구를 써서 성공한 작업을 재사용 가능한 절차로 증류), 사용자 모델과 저널이 붙어 쓸수록 사용자에게 맞춰진다.

## 누구를 위한 것인가

- 로컬 모델(Ollama, vLLM)이나 클라우드 모델(Anthropic, OpenAI, Gemini)을 바꿔 가며 쓰고 싶은 개인
- 터미널에서 파일, 셸, 웹 검색을 도구로 쓰는 에이전트가 필요하고, 위험한 명령은 사람이 승인하길 바라는 개발자
- 스케줄 알림, 열린 약속 추적, 먼저 말 거는 비서가 필요한 사람

## 두 가지 화면

| 화면 | 실행 | 특징 |
|---|---|---|
| TUI | `jarvis` | 터미널. 사고 패널 💭, 승인 프롬프트, 음성 입출력(Ctrl+R, Ctrl+T) |
| Web HUD | `jarvis --web` 또는 `docker compose --profile web up` | http://localhost:7777. 리액터 구체를 중심으로 AGENDA, ACTIVITY, SYSTEM, SESSIONS, CONVERSATION 카드. 구체 클릭으로 음성 모드 |

둘은 같은 백엔드 세션을 쓴다. 화면이 하나도 열려 있지 않아도 스케줄 결과와 먼저 건네는 말은 Slack 으로 보낼 수 있다.

## 문서 구성

- [구현 철학](./philosophy.md): 멱등성, 최소주의, 계층 규칙, 사고와 응답의 분리
- [서비스 기능 지도](./services.md): 기능 전체 목록, 기능별 아키텍처 설계도, 동작 흐름도로 가는 길
- [아키텍처](./architecture.md): 계층과 요청 한 번의 흐름
- [주요 기능](/features): 기능마다 동작 흐름과 구현 위치
- [이용 방법](/usage): 설치, 설정, Web HUD 와 TUI 사용법, 슬래시 커맨드, 확장, 문제 해결

API 와 화면의 정본 명세는 레포의 `docs/api-spec.md`, `docs/screen-spec.md` 다. 이 문서는 그 명세를 설명하는 쪽이고, 둘이 다르면 명세가 맞다.
