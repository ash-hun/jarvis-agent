---
sidebar_position: 1
slug: /intro
title: JARVIS-Agent 소개
---

# JARVIS-Agent 소개

<div align="center">
  <img src="/jarvis-agent/img/hud-motion.gif" alt="Web HUD 화면. 내적 사고, 마크다운 응답, 먼저 건네는 말, 승인 기억이 차례로 보인다" />
</div>

## 서비스 개요

보통의 채팅 에이전트는 사용자가 말해야 움직인다. JARVIS 는 요청마다 메인 응답과 따로 한 번 더 생각하고([내적 사고](../concepts/inner-thought.md)), 그 판단으로 다음 네 가지를 정한다.

- 지금 바로 답할지, "잠깐만요, 확인할게요" 를 먼저 말하고 뒤에서 처리할지
- 대화에서 흘린 약속과 끝내지 못한 일을 기억해 둘지
- 요청이 없는 시간에 스스로 성찰해서 먼저 말을 걸지, 침묵할지
- 먼저 건넨 말이 도움이 됐는지 배우고 다음 발화 기준을 조정할지

JARVIS 는 쓸수록 사용자에게 맞춰진다. 한 번 허용한 명령 패턴은 다시 묻지 않고(승인 기억), 여러 도구로 성공한 작업은 다시 쓸 수 있는 절차로 남기고(절차 학습), 대화에서 사용자 성향을 뽑아 사용자 모델과 저널로 쌓는다.

## 이런분들께 추천드립니다

- 로컬 모델(Ollama, vLLM)과 클라우드 모델(Anthropic, OpenAI, Gemini)을 바꿔 가며 쓰고 싶은 개인
- 파일, 셸, 웹 검색을 도구로 쓰는 에이전트가 필요하지만, 위험한 명령은 사람이 승인하길 바라는 개발자
- 스케줄 알림, 약속 추적, 먼저 말을 거는 비서가 필요한 사람

## 인터페이스

| 화면 | 실행 | 특징 |
|---|---|---|
| TUI | `jarvis` | 터미널. 사고 패널 💭, 승인 프롬프트, 음성 입출력(Ctrl+R, Ctrl+T) |
| Web HUD | `jarvis --web` 또는 `docker compose --profile web up` | http://localhost:7777. 리액터 구체를 가운데 두고 AGENDA, ACTIVITY, SYSTEM, SESSIONS, CONVERSATION 카드를 둘렀다. 구체를 누르면 음성 모드 |

두 화면은 같은 백엔드 세션을 쓴다. 화면을 하나도 열지 않아도 스케줄 결과와 먼저 건네는 말을 Slack 으로 받을 수 있다.

:::note[Notes]

- 바로 써 보려면 [Quick Start](./install.md) 다음 [첫 대화](../concepts/first-chat.md)를 따라간다.
- 어떻게 동작하는지 알고 싶으면 [기능 목록](../concepts/services.md)에서 시작한다.
- 설정 키나 명령을 찾으면 [환경설정](/reference)를 연다.
- 낯선 말이 나오면 [용어집](../reference/glossary.md)을 본다.

:::
