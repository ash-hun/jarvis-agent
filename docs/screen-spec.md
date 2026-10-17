# Jarvis Web HUD 화면기능 명세

| 항목 | 값 |
|---|---|
| Last Updated | 2026-10-17 |
| 소스 | `src/jarvis/ui/web/static/` (`index.html`, `styles.css`, `app/*.js`, `hud.js`, `sphere.js`, `voice.js`, `sw.js`) |
| 범위 | 브라우저 Web HUD. 터미널 TUI(`src/jarvis/ui/tui/`)는 이 문서 밖 |

> `Last Updated`는 **문서 내용이 실제로 바뀐 날**만 적는다.

## 화면 목록

경로 알파벳순.

| 경로 | 화면 | 목적 | 상태 |
|---|---|---|---|
| `/` | HUD | 에이전트와 대화하고 옆 카드로 상태를 본다 | 구현됨 |

화면은 하나다. 세션 전환은 URL 이 아니라 WebSocket 재연결로 한다. 그 외 경로는 nginx 가 `index.html` 로 돌려준다.

---

## 화면별 상세

### `/` HUD

**목적**: 가운데 리액터를 중심으로, 왼쪽에 에이전트 상태 카드, 오른쪽에 세션과 대화를 둔다. 접속하면 바로 `default` 세션(JARVIS)에 붙는다. 화면의 이름, 명언, 색(링, 구체, CSS 변수)은 지금 세션 에이전트의 것이다.

**레이아웃**: 헤더, 3열 스테이지, 하단 입력 독.

```
┌──────────────────────────────────────────────────────────────┐
│ SYS:ONLINE / 버전  J.A.R.V.I.S.  [DEFAULT|FULL-VOICE] READY 시각 │ 헤더
├───────────────┬──────────────────────────┬───────────────────┤
│ AGENDA        │                          │ SESSIONS        + │
│  UPCOMING     │        리액터(구체)       │ [JARVIS][KAREN]   │
│               │                          │  default  NOW ⑂   │
│  OPEN LOOPS   │                          │                   │
├───────────────┤       ● ACTIVE           ├───────────────────┤
│ ACTIVITY      │       "명언" / 마지막 줄  │ CONVERSATION      │
├───────────────┤                          │  USER / J.A.R.V.I.S│
│ SYSTEM        │                          │  💭  🔔  SYS      │
│  MODEL…COST   │                          │                   │
│  TOOLS ▾      │                          │                   │
├───────────────┴──────────────────────────┴───────────────────┤
│ >_ [입력창                              ]  [SEND ⏎]          │ 입력 독
└──────────────────────────────────────────────────────────────┘
```

열 안은 세로 flex 다. 카드를 접으면 아래 카드가 그 자리를 채운다. ACTIVITY 는 최소 96px 를 지킨다. 860px 이하에서는 왼쪽 열이 드로어가 되고(헤더의 ≡ 버튼), 리액터 아래에 SESSIONS 와 CONVERSATION 이 온다.

**Focus 레이아웃** (`body[data-focus="on"]`, `/focus <작업>` 동안):

```
┌──────────────────────────────────────────────────────────────┐
│ SYS:ONLINE        J.A.R.V.I.S. [FOCUS]     [모드] READY 시각  │
├─┬──────────────────────┬───────────┬───────────────────────┬─┤
│A│ REFERENCE  조사 및 종합│  ╭─────╮  │ ANALYSIS 목적, 필요…   │S│
│G│  선례, 출처, 적용할 점 │ (  구체  ) │  근본 목적 … 미리 대비 │E│
│E│                      │  ╰─────╯  │                       │S│
│N├──────────────────────┤  ● ACTIVE ├───────────────────────┼─┤
│D│ LOG  작업 기록         │           │ PROGRESS        경과   │C│
│A│  시각별 3인칭 기록     │           │  33%       약 21분 남음│O│
│…│                      │           │  ✓ 단계 ○ 단계         │N│
├─┴──────────────────────┴───────────┴───────────────────────┴─┤
│ >_ [입력창                              ]  [SEND ⏎]          │
└──────────────────────────────────────────────────────────────┘
```

좌우 카드는 머리글만 세로로 세운 30px 띠가 된다. 구체는 70% 크기에 채도와 밝기가 오르고, 둘레에 네 영역 쪽으로 뻗는 호가 그려진다. 들어갈 때는 띠 접힘, 구체 축소, 호, 네 영역 순으로 약 1.2초, 나올 때는 거꾸로 간다. 860px 이하에서는 구체 아래로 PROGRESS, REFERENCE, ANALYSIS, LOG 를 쌓고 맨 아래에 CONVERSATION 막대만 둔다.

**데이터**

| 출처 | 호출 | 쓰이는 곳 |
|---|---|---|
| WS `connected` | 접속 직후 | SYSTEM 의 MODEL, SESSION, 세션 목록과 각 세션의 에이전트(`session_agents`), 세션 에이전트의 이름과 색(`agent`), 슬래시 명령, 음성 STT 모드 |
| `GET /api/sessions/{id}/messages` | 접속, 세션 전환 직후 | CONVERSATION 복원(마크다운 렌더) |
| `GET /api/agenda` | 접속, `inner_thought`, `agent_end`, open loop 나 스케줄 조작 직후, 1분마다 | AGENDA |
| `GET /api/agents` | 첫 접속 때 한 번 | 에이전트 칩, 세션 표식 색, AGENDA 항목의 에이전트 라벨 |
| `POST /api/sessions {agent}` | `+`, 열린 세션이 없는 에이전트 칩 클릭 | 그 에이전트의 새 세션 |
| `GET /api/tools?session_id=` | 접속, `agent_end` | SYSTEM 의 TOOLS(지금 세션 에이전트의 도구) |
| `POST /api/openloops/{id}` | ✓ / ✕ 클릭 | open loop 닫기 |
| `POST /api/schedules/{name}` | 스위치 클릭 | 스케줄 켜기/끄기 |
| `POST /api/sessions` | `+` 클릭 | 새 세션 |
| `POST /api/sessions/{id}/branch` | ⑂ 클릭 | 세션 분기 |
| `DELETE /api/sessions/{id}` | ✕ 클릭 후 확인 | 세션 삭제. 목록은 `GET /api/sessions` 로 다시 그린다 |
| `GET /brand.js` | 페이지 로드 | 이름, 명언, 색 |
| WS 이벤트 전부 | 연결 중 | CONVERSATION, 상태 pill, 리액터 상태, ACTIVITY, 사용량 |
| WS `agent_activity`, `connected.active_agents` | 어느 에이전트든 일을 시작하거나 끝낼 때 | 에이전트 칩의 빛남, 구체 색 섞기, ACTIVITY `⇄ A · B 함께 작업 중` |
| WS `focus_state` | `/focus` 시작, 매 턴의 진행 갱신, 종료, 진행 중인 작업이 있는 세션에 접속 | Focus 레이아웃 켜고 끄기, PROGRESS(작업, 퍼센트, 막대, 예상 시간, 단계), ACTIVITY `◎ focus · N%` |
| WS `focus_panel` | sub-agent 가 영역을 갱신하기 시작할 때(`busy`)와 끝낼 때 | REFERENCE, ANALYSIS, LOG 본문(마크다운). 갱신 중이면 머리글에 `SYNC` |

**상태와 파라미터**

| 이름 | 위치 | 기본값 | 효과 |
|---|---|---|---|
| `session_id` | WS 쿼리 | `default` | 어느 세션에 붙는지. 화면 안에서만 바뀐다 |
| 함께 일하는 에이전트 | `agent_activity.active` | 빈 목록 | 둘 이상이면 구체 입자가 그 에이전트들의 primary 두 색으로 흐르는 띠처럼 섞인다(지금 에이전트 색이 먼저, 약 1초에 걸쳐 섞이고 끝나면 같은 속도로 돌아온다). 일하는 에이전트 칩은 숨쉬듯 빛난다 |
| 세션 에이전트 | `connected.agent`, `html[data-agent]` | `main` | 이름, 명언, 색. 바뀌면 `jarvis:palette` 이벤트로 링(hud.js)과 구체(sphere.js)가 새 색을 쓴다. 새로고침하면 `default`(JARVIS)로 돌아간다 |
| `jarvis_token` | localStorage | 없음 | 접근 키. `4401` 로 끊기면 `prompt()` 로 묻고 저장 |
| `hud.chatCollapsed` | localStorage | `0` | CONVERSATION 접힘 |
| `hud.sessionsCollapsed` | localStorage | `0` | SESSIONS 접힘 |
| `hud.mode` | localStorage, `body[data-mode]` | `default` | `default` 또는 `full-voice`. 모르는 값이면 `default`. 새로고침 뒤에도 유지되지만 마이크는 사용자 클릭 전에는 켜지 않는다 |
| 상태 pill | 메모리 | `READY` | `THINKING`(서브 에이전트면 `THINKING · a → b`), `EXECUTING`, `LISTENING`, `SPEAKING`, `ERROR` |
| 리액터 상태 | `window.HUD.state` | `idle` | `thinking`, `tool_running`, `listening`, `speaking`, `error`. 링 발광과 구체 움직임이 따라간다 |
| 음성 모드 | 메모리 | 꺼짐 | 구체 클릭으로 토글. 켜져 있으면 응답과 🔔 를 읽어준다. Full-voice 에서는 입력 방식과 상관없이 늘 읽는다 |
| Focus | `body[data-focus]`, 서버의 `focus_state` | 꺼짐 | 세션마다 하나. 화면은 저장하지 않고 서버가 접속 때 다시 보낸다. 세션을 바꾸면 일단 끄고 그 세션의 상태를 기다린다. 헤더 DEFAULT / FULL-VOICE 와는 별개라 함께 켤 수 있다 |
| 펼친 대화 | `body.focus-chat-open` | 꺼짐 | Focus 동안 CONVERSATION 띠를 눌렀을 때 |

**인터랙션**

| 사용자 행동 | 결과 |
|---|---|
| 입력 후 Enter 또는 SEND | USER 메시지 추가, 입력 잠금, THINKING 자리표시(점 애니메이션). 첫 `agent_start` 에서 스트리밍 메시지로 바뀐다. 90초 안에 아무 이벤트도 없으면 자리표시를 지우고 READY 로 |
| `/` 로 시작하는 입력 | 자동완성 팝업. ↑↓ 이동, Enter/Tab 선택(입력창에 `/명령 ` 삽입, 한 번 더 Enter 가 전송), Esc 닫기. 문장 중간의 `/명령` 도 하이라이트 |
| 🔔 뒤 짧은 답(`네`, `좋아`, `고마워` / `아니오`, `됐어`, `무시` 등 완전 일치) | `proactive_feedback` 만 보내고 `피드백: 도움됨/무시` 한 줄. LLM 으로 가지 않고 입력은 열린 채 |
| 🔔 뒤 그 밖의 40자 이하 답("응 그걸로 해줘") | 사고가 켜져 있으면(`connected.reply_classifier`) 입력을 잠그고 `reply_classify` 로 묻는다. `accept`/`dismiss` 면 `피드백: 도움됨 (분류)` 처럼 한 줄(학습은 서버가 함), `other` 거나 8초 안에 답이 없으면 보통 메시지로 보낸다. 40자보다 길거나 사고가 꺼져 있으면 묻지 않고 보통 메시지 |
| 🔔 뒤 다른 말 | 보통 메시지로 전송. 질문 줄은 흐려진다 |
| 💭 한 줄 클릭 | 💭 와 `▸ decision · 확신도` 가 한 줄. 클릭하면 해석 전문이 그 아래로 펼쳐진다. 다시 클릭하면 접힘 |
| 카드 헤더(SESSIONS, CONVERSATION) 클릭 | 접기/펼치기. 헤더 안의 `+` 는 접기가 아니다 |
| SESSIONS 의 세션 이름 클릭 | 그 세션으로 재연결. 대화, 사용량, 아티팩트 초기화 후 히스토리 복원. 세션 앞 네모 표식은 그 세션 에이전트의 색 |
| `+` | 지금 에이전트의 새 세션 생성 후 연결 |
| SESSIONS 의 에이전트 칩(에이전트가 둘 이상일 때만 보임) | 그 에이전트의 열린 세션 중 목록에서 가장 위의 것(에이전트끼리의 대화 세션 `peer-…` 제외)으로 연결, 없으면 새로 만든다. 연결되면 이름, 명언, 링, 구체, 패널 색이 그 에이전트 것으로 바뀐다. 지금 에이전트 칩은 채워진 색 |
| 활성 세션의 ⑂ | 분기 생성 후 연결 |
| 비활성 세션의 ✕ (행에 마우스를 올리면 보임) | `confirm()` 뒤 삭제. 보고 있는 세션은 ✕ 가 없다. 409 면 ACTIVITY 에 `세션 삭제 실패` |
| AGENDA 의 ✓ / ✕ | open loop 를 done / dismissed 로. 항목이 사라지고 ACTIVITY 에 한 줄. 다른 에이전트의 약속도 닫을 수 있다 |
| AGENDA 의 스위치 | 스케줄 켜기/끄기 |
| TOOLS ▾ | 도구 목록 펼침. 🔒 는 승인 필요 도구 |
| 승인 모달의 `ALLOW` / `ALWAYS · 패턴` / `DENY`, Enter | `approval_response`. ALWAYS 는 서버가 패턴을 제안했을 때만 보인다. Enter 는 ALLOW. 같은 세션의 다른 창이 먼저 답하면 `approval_resolved` 로 모달이 닫히고 ACTIVITY 에 `다른 창에서 처리됨` |
| 구체 클릭 | 음성 모드 토글. 읽는 중(합성 대기 포함)이면 읽기를 멈춘다. 미지원 브라우저면 SYS 에러 한 줄 |
| 헤더의 DEFAULT / FULL-VOICE | 모드 전환. 좁은 화면(560px 이하)에서는 DEF / VOICE. 같은 쪽을 다시 누르면 아무 일 없음. FULL-VOICE 로 바꾸면 바로 듣기 시작. 음성 미지원 브라우저면 SYS 에러 후 DEFAULT 로 돌아간다. DEFAULT 로 바꾸면 듣던 것을 멈춘다 |
| Full-voice: 응답 끝 | 응답을 읽고, 다 읽으면 다시 듣는다(LISTENING). 말이 없으면 READY 로 멈춘다 |
| 음성 승인 요청 (Full-voice, 또는 Default 에서 음성으로 시작한 요청) | 모달을 띄운 채 `명령 X 를 실행할까요. 허용, 항상, 거부.` 를 읽고 듣는다(항상은 패턴 제안이 있을 때만). 답은 거부 쪽으로 기운다. 부정어(거부, 아니, 안 돼, 하지 마, 취소 등)가 있으면 DENY, 항상(패턴 있을 때)은 ALWAYS, 허용, 승인, 실행해 같은 긍정이나 `네`, `응`, `좋아` 단독이면 ALLOW. 그 밖의 말("그거 돌려")은 `reply_classify` 로 묻고 `allow`/`always` 일 때만 허용, `deny`/`unclear`, 시간 초과, 사고 꺼짐은 DENY. 분류를 기다리는 사이 모달이 클릭이나 다른 창으로 닫히면 음성 답은 버린다. 결과를 `허용으로 들었습니다` 처럼 되읽고 SYS 한 줄, ACTIVITY 한 줄. 되읽은 뒤에는 듣지 않는다. 읽는 동안 모달을 클릭으로 답하면 다 읽어도 듣지 않는다 |
| Full-voice: 마이크 | 켜는 클릭 뒤 첫 듣기에서 마이크 스트림을 잡고 Default 로 돌아갈 때까지 놓지 않는다. 블루투스 헤드셋이 듣기와 읽기 사이에 통화, 음악 프로필을 오가지 않게 하려는 것으로, 그동안 출력은 통화 음질이다. 권한이 없으면 잡지 않고 매번 열고 닫는다 |
| 음성 읽기 시점 | 인식이 열려 있으면 닫힐 때까지(최대 1.5초) 기다리고, 닫힌 뒤 0.6초를 더 쉰 다음 읽는다. 헤드셋이 오디오 경로를 다시 잡는 사이 짧은 문장(승인 되읽기)이 사라지는 것을 막는다. 브라우저 TTS 가 1.5초 안에 시작하지 않으면 한 번만 다시 읽고, 콘솔에 `[voice] tts ...` 를 남긴다 |
| Full-voice: 🔔 | 본문과 `이 제안이 도움이 됐나요? 네 또는 아니오로 답해 주세요.` 를 읽고 듣는다. 답은 🔔 짧은 답 규칙과 같다. 💬 filler 는 읽기만 한다 |
| Ctrl+K | `abort` 전송, 스트림 종료, 입력 복원 |
| Esc | 드로어 닫기. 읽는 중(합성 대기 포함)이면 읽기도 멈춘다. 멈춘 뒤엔 Full-voice 라도 다시 듣지 않고, 늦게 온 합성 결과는 버린다 |
| `/focus <작업>` 전송, 음성 "포커스 모드 <작업>" | Focus 시작. 안내 한 줄 뒤 레이아웃이 바뀌고, 첫 분석과 단계 계획이 나오면(최대 30초) 작업 문장으로 첫 응답을 시작한다. 이미 작업이 있으면 거절 안내만 |
| `/focus stop`, 음성 "포커스 모드 종료" / "포커스 종료" | Focus 종료, Default 레이아웃으로 돌아간다. 응답 중에는 입력창이 잠겨 있어 끝난 뒤에 보낼 수 있다 |
| `/focus` | 진행률과 단계를 대화에 한 번 보여준다 |
| Focus: CONVERSATION 띠 클릭 | 대화를 오른쪽 띠 옆에 덮어 띄운다. 다시 누르거나 대화, 입력 독 밖을 누르면 닫힌다. 다른 띠(AGENDA, ACTIVITY, SYSTEM, SESSIONS)는 눌러도 반응하지 않는다 |
| 코드블록의 COPY | 클립보드 복사. 8줄 이상 코드블록이 응답에 있으면 오른쪽 아티팩트 패널에도 뜬다(COPY, ✕) |
| 응답에 `/schedule` 포함해 전송 | 브라우저 알림 권한을 그때 묻는다 |

**빈 상태**

CONVERSATION: 히스토리가 없으면 `— SESSION · 시각 · id —` 한 줄만. AGENDA: `예정된 작업 없음`, `남은 할 일 없음`(CSS `data-empty`). TOOLS: 0. ACTIVITY: 접속 줄 하나. 리액터 캡션: 명언.

**에러 상태**

WS 끊김: 상단 배너 `연결 끊김 — 재연결 중...`, 입력 잠금, 1초부터 2배씩 최대 10초 간격으로 재접속. `4401`: 키 입력 `prompt()`, 취소하면 배너와 ACTIVITY `접근 키 없음`. `agent_error`, `error`: SYS 에러 메시지 + 상태 `ERROR` 3초 뒤 READY. `/api/agenda`, `/api/tools` 실패: 콘솔 경고만, 화면은 이전 값 유지. 히스토리 실패: 콘솔 에러, 빈 대화. 승인 요청 120초 무응답: 서버가 거부로 처리하고 도구 결과에 `denied` 가 온다. 음성 TTS 오류: `error` 로 와서 음성 상태가 풀린다.

---

## 공통 컴포넌트

| 컴포넌트 | 위치 | 받는 것 | 쓰는 화면 |
|---|---|---|---|
| `panel-head` + `setupCollapse` | `shell.js` | 토글 id, body 클래스, localStorage 키 | SESSIONS, CONVERSATION |
| 메시지(`appendMsg`, `appendThought`, 스트림, 도구 흔적, 대기 자리표시, 히스토리) | `messages.js` | 역할 라벨, 종류, HTML | CONVERSATION |
| 마크다운 렌더(`renderMarkdown`, `attachCopyBtns`) | `markdown.js` | 텍스트 | 응답, 히스토리, 🔔, 스케줄 작업 알림 |
| 승인 오버레이, 음성 답 해석(`parseApprovalAnswer`) | `approval.js` | `approval_request`, 전사 텍스트 | 전역 모달 |
| 모드 세그먼트 | `mode.js` | 클릭, `hud.mode` | 헤더 |
| 슬래시 팝업, 입력 하이라이트 | `composer.js` | 명령 목록 | 입력 독 |
| 아티팩트 패널 | `artifact.js` | 언어, 코드 | 오른쪽 슬라이드 패널 |
| 리액터 캔버스(링, 눈금, 별), 입자 구 | `hud.js`, `sphere.js` | `HUD.state`, `BRAND.palette` | 가운데 |
| 음성(`VoiceManager`) | `voice.js`, `voice-ui.js` | 브라우저 Web Speech 또는 서버 STT/TTS | 구체, 입력 |
| 연결 배너, 드로어, 스크림 | `index.html`, `shell.js` | 연결 상태, 뷰포트 폭 | 전역 |
| 서비스 워커 | `sw.js` | 셸 파일 목록 | 오프라인 폴백. 셸은 네트워크 우선 |
| Focus 영역, 음성 키워드(`focusCommandFromSpeech`) | `focus.js` | `focus_state`, `focus_panel`, 전사 텍스트 | 리액터 둘레, 헤더 FOCUS 표시 |

---

## 미구현 / 알려진 제약

- 키워드가 아닌 🔔 답은 분류를 기다리는 1~2초(첫 호출은 모델 로딩으로 4초쯤) 동안 입력이 잠긴다. 사고 모델이 그 🔔 와 무관한 새 요청을 accept/dismiss 로 잘못 읽으면 그 말은 보내지지 않는다. 실측(gemma4:e2b, 11문장)에서는 없었다.
- 음성 승인 답은 부정어가 있으면 분류 없이 거부한다. "허용 안 해" 처럼 긍정과 부정이 섞인 말은 늘 거부다.
- Full-voice 동안 마이크를 잡아 두므로 브라우저의 녹음 표시가 계속 켜져 있고, 블루투스 헤드셋은 통화 음질로 읽는다.
- Full-voice 의 자동 듣기는 읽기가 끝난 직후 한 번뿐이다. 말이 없으면 멈추고, 다시 시작하려면 구체를 누른다.
- 읽기가 겹치면(💬 filler 를 읽는 중에 승인 요청이 오면) 소리가 겹치고, 먼저 끝난 쪽에서 듣기가 시작될 수 있다.
- Focus 동안에도 🔔 는 그대로 뜬다. 세션 단위로 끄려면 서버 쪽 게이팅이 필요하다.
- Focus 의 진행률은 진행 sub-agent 가 매긴 단계 완료로 계산한다. 단계를 늘리면 퍼센트가 내려간다. 예상 시간은 지금까지 걸린 시간 / 완료 단계 수 × 남은 단계 수라, 완료 단계가 없으면 `예상 시간 계산 중` 이다.
- Focus 의 분석은 지시가 들어올 때 메인 응답과 같이 돈다. 그 결과는 이번 응답이 아니라 다음 응답의 시스템 프롬프트에 들어간다(첫 지시만 시작할 때 기다려서 첫 응답에 넣는다).
- 세션 목록은 프로세스가 띄운 것만 보인다. 저장소에만 있는 세션은 화면에 없다.
- Postgres 저장소에서 ⑂ 분기는 빈 새 세션이다. 히스토리가 복사되지 않는다.
- open loop 중복 판정은 정규화 일치, 포함 관계(6자 이상), 임베딩 코사인 0.85 이상(`JARVIS_MEMORY__EMBEDDING_*` 설정이 있을 때), 글자 bigram 겹침(Jaccard 0.4 이상)이다. 뜻이 멀게 바꾼 약속("운동 등록" 과 "헬스장 회원권")은 따로 쌓인다.
- open loop 는 ✓ / ✕ 말고도, 대화에서 끝났거나 취소됐다고 사고가 판단하면 done 으로, 사용자가 취소하는 말로 가리키면 dismissed 로, 기한이 지나면 expired 로 저절로 닫혀 AGENDA 에서 빠진다. 잘못 닫힌 것을 되살리는 화면은 없다.
- 사용자 입력과 글자가 거의 겹치지 않는 새 약속은 저장하지 않는다. 입력과 전혀 다른 말로 바꿔 적은 약속은 AGENDA 에 오지 않는다.
- 구체 색 섞기는 두 색까지다. 세 에이전트가 함께 일해도 앞의 두 색만 섞인다. 링과 패널 색은 지금 에이전트 그대로다.
- 에이전트끼리의 대화(`peer-<부른 쪽>-<받는 쪽>` 세션)는 세션 목록에 다른 세션처럼 보인다. 눌러서 받는 쪽 대화를 볼 수 있다.
- AGENDA 는 모든 에이전트의 스케줄과 약속을 한 목록에 섞어 보여준다. 에이전트가 둘 이상일 때만 항목 시각 앞에 에이전트 이름 라벨(그 에이전트의 primary 색)이 붙는다. 에이전트별로 거르는 필터는 없다.
- open loop 는 닫기만 되고 수정과 되살리기는 없다. 스케줄은 켜고 끄기만 되고 만들기와 지우기는 슬래시 명령(`/schedule`)으로.
- 음성 TTS 요청에 서버가 응답하지 않으면 `음성 처리 중` 상태에 머문다(서버가 빈 `voice_tts_audio` 를 돌려주는 것으로 막고 있다).
- 오른쪽 아티팩트 패널은 응답 하나에 코드블록 하나만 보여준다(가장 긴 것).
- 입력창은 한 줄이다. 줄바꿈 입력 없음.
- TUI 는 이 문서 범위 밖. 같은 백엔드를 쓰지만 화면 구성이 다르다.
