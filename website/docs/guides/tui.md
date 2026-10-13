---
sidebar_position: 2
title: TUI 사용법
---

# TUI 사용법

TUI 는 터미널에서 JARVIS 와 대화하는 화면이다. `jarvis` 를 실행하면 `default` 세션이 열리고, `jarvis -s <id>` 를 실행하면 기존 세션이 열린다.

TUI 는 Textual 앱(`ui/tui/app.py`)이다.

## 화면

- 헤더와 시계가 있다
- 사이드바(26칸)의 Sessions 는 최근 세션 10개를 트리로 보여 주고, 분기는 `↳` 로 표시한다. Tools 는 도구를 `⚙ name` 꼴로 나열한다
- 대화 로그에는 `You:`, `Jarvis:`, 도구 줄 `⛙ name [done|error]` 이 찍힌다. 💭 는 흐린 기울임 한 줄(해석, decision, 확신도)로 보이고, 💬 는 filler 다. 🔔 뒤에는 "ctrl+y 도움됨 / ctrl+g 무시" 힌트가 붙는다
- 그 밖에 슬래시 선택기, 입력창, 상태 줄(Ready, `Thinking… [main → agent]`, 음성 상태), 푸터가 있다

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

종료할 때 TUI 는 세 가지 일을 한다. 세션 요약을 일화 기억으로 저장하고, 일화에서 사실을 추출(통합)하고, 도구를 여러 번 써서 성공한 구간을 절차 초안으로 증류한다. 그래서 `Ctrl+C` 를 누른 뒤 꺼지기까지 조금 걸릴 수 있다.

## 인증

TUI 는 설정과 상관없이 로컬 사용자로 동작한다. `JARVIS_SECURITY__API_KEYS` 는 Web 에만 영향을 준다.
