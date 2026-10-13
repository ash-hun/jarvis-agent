---
sidebar_position: 2
title: TUI 사용법
---

# TUI 사용법

`jarvis` 로 `default` 세션, `jarvis -s <id>` 로 기존 세션. Textual 앱(`ui/tui/app.py`)이다.

## 화면

- 헤더와 시계
- 사이드바(26칸): Sessions 는 최근 10개를 트리로(분기는 `↳`), Tools 는 `⚙ name`
- 대화 로그: `You:`, `Jarvis:`, 도구 줄 `⛙ name [done|error]`, 💭 는 흐린 기울임 한 줄(해석, decision, 확신도), 💬 filler, 🔔 뒤에는 "ctrl+y 도움됨 / ctrl+g 무시" 힌트
- 슬래시 선택기, 입력창, 상태 줄(Ready, `Thinking… [main → agent]`, 음성 상태), 푸터

## 키

| 키 | 동작 |
|---|---|
| `Ctrl+C` | 종료. `/exit` 도 같다 |
| `Ctrl+K` | 현재 턴 중단 |
| `Ctrl+B` | 사이드바 토글 |
| `Ctrl+N` | 새 세션 |
| `Ctrl+F` | 현재 세션 분기 |
| `Ctrl+T` | 응답 읽어 주기 토글(TTS) |
| `Ctrl+R` | 녹음 → 전사 → 입력창에 채움 |
| `Ctrl+Y`, `Ctrl+G` | 마지막 🔔 에 도움됨, 무시 |
| 선택기 | ↑↓ 이동, Tab 완성, Enter 선택, Esc 닫기 |
| 승인 다이얼로그 | `y` 허용, `a` 항상 허용, `n` 또는 Esc 거부 |

## 종료 때 일어나는 일

세션 요약을 일화 기억으로 저장하고, 일화에서 사실을 추출(통합)하고, 도구를 여러 번 쓴 성공 구간을 절차 초안으로 증류한다. 그래서 `Ctrl+C` 가 조금 걸릴 수 있다.

## 인증

TUI 는 설정과 무관하게 로컬 사용자다. `JARVIS_SECURITY__API_KEYS` 는 Web 에만 영향을 준다.
