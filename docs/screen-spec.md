# Jarvis Web HUD 화면기능 명세

| 항목 | 값 |
|---|---|
| Last Updated | 2026-10-11 |
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

### `/` — HUD

**목적** — 가운데 리액터를 중심으로, 왼쪽에 에이전트 상태 카드, 오른쪽에 세션과 대화를 둔다. 접속하면 바로 `default` 세션에 붙는다.

**레이아웃** — 헤더, 3열 스테이지, 하단 입력 독.

```
┌──────────────────────────────────────────────────────────────┐
│ SYS:ONLINE / 버전  J.A.R.V.I.S.  [DEFAULT|FULL-VOICE] READY 시각 │ 헤더
├───────────────┬──────────────────────────┬───────────────────┤
│ AGENDA        │                          │ SESSIONS          │
│  UPCOMING     │        리액터(구체)       │  default  NOW ⑂   │
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

**데이터**

| 출처 | 호출 | 쓰이는 곳 |
|---|---|---|
| WS `connected` | 접속 직후 | SYSTEM 의 MODEL, SESSION, 세션 목록, 슬래시 명령, 음성 STT 모드 |
| `GET /api/sessions/{id}/messages` | 접속·세션 전환 직후 | CONVERSATION 복원(마크다운 렌더) |
| `GET /api/agenda` | 접속, `inner_thought`, `agent_end`, open loop·스케줄 조작 직후, 1분마다 | AGENDA |
| `GET /api/tools` | 접속, `agent_end` | SYSTEM 의 TOOLS |
| `POST /api/openloops/{id}` | ✓ / ✕ 클릭 | open loop 닫기 |
| `POST /api/schedules/{name}` | 스위치 클릭 | 스케줄 켜기/끄기 |
| `POST /api/sessions` | `+` 클릭 | 새 세션 |
| `POST /api/sessions/{id}/branch` | ⑂ 클릭 | 세션 분기 |
| `DELETE /api/sessions/{id}` | ✕ 클릭 후 확인 | 세션 삭제. 목록은 `GET /api/sessions` 로 다시 그린다 |
| `GET /brand.js` | 페이지 로드 | 이름, 명언, 색 |
| WS 이벤트 전부 | 연결 중 | CONVERSATION, 상태 pill, 리액터 상태, ACTIVITY, 사용량 |

**상태·파라미터**

| 이름 | 위치 | 기본값 | 효과 |
|---|---|---|---|
| `session_id` | WS 쿼리 | `default` | 어느 세션에 붙는지. 화면 안에서만 바뀐다 |
| `jarvis_token` | localStorage | 없음 | 접근 키. `4401` 로 끊기면 `prompt()` 로 묻고 저장 |
| `hud.chatCollapsed` | localStorage | `0` | CONVERSATION 접힘 |
| `hud.sessionsCollapsed` | localStorage | `0` | SESSIONS 접힘 |
| `hud.mode` | localStorage, `body[data-mode]` | `default` | `default` 또는 `full-voice`. 모르는 값이면 `default`. 새로고침 뒤에도 유지되지만 마이크는 사용자 클릭 전에는 켜지 않는다 |
| 상태 pill | 메모리 | `READY` | `THINKING`(서브 에이전트면 `THINKING · a → b`), `EXECUTING`, `LISTENING`, `SPEAKING`, `ERROR` |
| 리액터 상태 | `window.HUD.state` | `idle` | `thinking`, `tool_running`, `listening`, `speaking`, `error`. 링 발광과 구체 움직임이 따라간다 |
| 음성 모드 | 메모리 | 꺼짐 | 구체 클릭으로 토글. 켜져 있으면 응답과 🔔 를 읽어준다. Full-voice 에서는 입력 방식과 상관없이 늘 읽는다 |

**인터랙션**

| 사용자 행동 | 결과 |
|---|---|
| 입력 후 Enter 또는 SEND | USER 메시지 추가, 입력 잠금, THINKING 자리표시(점 애니메이션). 첫 `agent_start` 에서 스트리밍 메시지로 바뀐다. 90초 안에 아무 이벤트도 없으면 자리표시를 지우고 READY 로 |
| `/` 로 시작하는 입력 | 자동완성 팝업. ↑↓ 이동, Enter/Tab 선택(입력창에 `/명령 ` 삽입, 한 번 더 Enter 가 전송), Esc 닫기. 문장 중간의 `/명령` 도 하이라이트 |
| 🔔 뒤 짧은 답(`네`, `좋아`, `고마워` / `아니오`, `됐어`, `무시` 등 완전 일치) | `proactive_feedback` 만 보내고 `피드백: 도움됨/무시` 한 줄. LLM 으로 가지 않고 입력은 열린 채 |
| 🔔 뒤 다른 말 | 보통 메시지로 전송. 질문 줄은 흐려진다 |
| 💭 한 줄 클릭 | 💭 와 `▸ decision · 확신도` 가 한 줄. 클릭하면 해석 전문이 그 아래로 펼쳐진다. 다시 클릭하면 접힘 |
| 카드 헤더(SESSIONS, CONVERSATION) 클릭 | 접기/펼치기. 헤더 안의 `+` 는 접기가 아니다 |
| SESSIONS 의 세션 이름 클릭 | 그 세션으로 재연결. 대화·사용량·아티팩트 초기화 후 히스토리 복원 |
| `+` | 새 세션 생성 후 연결 |
| 활성 세션의 ⑂ | 분기 생성 후 연결 |
| 비활성 세션의 ✕ (행에 마우스를 올리면 보임) | `confirm()` 뒤 삭제. 보고 있는 세션은 ✕ 가 없다. 409 면 ACTIVITY 에 `세션 삭제 실패` |
| AGENDA 의 ✓ / ✕ | open loop 를 done / dismissed 로. 항목이 사라지고 ACTIVITY 에 한 줄 |
| AGENDA 의 스위치 | 스케줄 켜기/끄기 |
| TOOLS ▾ | 도구 목록 펼침. 🔒 는 승인 필요 도구 |
| 승인 모달의 ALLOW / ALWAYS · 패턴 / DENY, Enter | `approval_response`. ALWAYS 는 서버가 패턴을 제안했을 때만 보인다. Enter 는 ALLOW. 같은 세션의 다른 창이 먼저 답하면 `approval_resolved` 로 모달이 닫히고 ACTIVITY 에 `다른 창에서 처리됨` |
| 구체 클릭 | 음성 모드 토글. 미지원 브라우저면 SYS 에러 한 줄 |
| 헤더의 DEFAULT / FULL-VOICE | 모드 전환. 좁은 화면(560px 이하)에서는 DEF / VOICE. 같은 쪽을 다시 누르면 아무 일 없음. FULL-VOICE 로 바꾸면 바로 듣기 시작. 음성 미지원 브라우저면 SYS 에러 후 DEFAULT 로 돌아간다. DEFAULT 로 바꾸면 듣던 것을 멈춘다 |
| Full-voice: 응답 끝 | 응답을 읽고, 다 읽으면 다시 듣는다(LISTENING). 말이 없으면 READY 로 멈춘다 |
| Full-voice: 승인 요청 | 모달을 띄운 채 `명령 X 를 실행할까요. 허용, 항상, 거부.` 를 읽고 듣는다(항상은 패턴 제안이 있을 때만). 답은 거부 쪽으로 기운다. 부정어(거부, 아니, 안 돼, 하지 마, 취소 등)가 있으면 DENY, 항상(패턴 있을 때)은 ALWAYS, 허용, 승인, 실행해 같은 긍정이나 `네`, `응`, `좋아` 단독이면 ALLOW, 나머지는 DENY. 결과를 `허용으로 들었습니다` 처럼 되읽고 SYS 한 줄, ACTIVITY 한 줄. 되읽은 뒤에는 듣지 않는다. 읽는 동안 모달을 클릭으로 답하면 다 읽어도 듣지 않는다 |
| Full-voice: 마이크 | 켜는 클릭 뒤 첫 듣기에서 마이크 스트림을 잡고 Default 로 돌아갈 때까지 놓지 않는다. 블루투스 헤드셋이 듣기와 읽기 사이에 통화, 음악 프로필을 오가지 않게 하려는 것으로, 그동안 출력은 통화 음질이다. 권한이 없으면 잡지 않고 매번 열고 닫는다 |
| 음성 읽기 시점 | 인식이 열려 있으면 닫힐 때까지(최대 1.5초) 기다리고, 닫힌 뒤 0.6초를 더 쉰 다음 읽는다. 헤드셋이 오디오 경로를 다시 잡는 사이 짧은 문장(승인 되읽기)이 사라지는 것을 막는다. 브라우저 TTS 가 1.5초 안에 시작하지 않으면 한 번만 다시 읽고, 콘솔에 `[voice] tts ...` 를 남긴다 |
| Full-voice: 🔔 | 본문과 `이 제안이 도움이 됐나요? 네 또는 아니오로 답해 주세요.` 를 읽고 듣는다. 답은 🔔 짧은 답 규칙과 같다. 💬 filler 는 읽기만 한다 |
| Ctrl+K | `abort` 전송, 스트림 종료, 입력 복원 |
| Esc | 드로어 닫기 |
| 코드블록의 COPY | 클립보드 복사. 8줄 이상 코드블록이 응답에 있으면 오른쪽 아티팩트 패널에도 뜬다(COPY, ✕) |
| 응답에 `/schedule` 포함해 전송 | 브라우저 알림 권한을 그때 묻는다 |

**빈 상태** — CONVERSATION: 히스토리가 없으면 `— SESSION · 시각 · id —` 한 줄만. AGENDA: `예정된 작업 없음`, `남은 할 일 없음`(CSS `data-empty`). TOOLS: 0. ACTIVITY: 접속 줄 하나. 리액터 캡션: 명언.

**에러 상태** — WS 끊김: 상단 배너 `연결 끊김 — 재연결 중...`, 입력 잠금, 1초부터 2배씩 최대 10초 간격으로 재접속. `4401`: 키 입력 `prompt()`, 취소하면 배너와 ACTIVITY `접근 키 없음`. `agent_error`, `error`: SYS 에러 메시지 + 상태 `ERROR` 3초 뒤 READY. `/api/agenda`, `/api/tools` 실패: 콘솔 경고만, 화면은 이전 값 유지. 히스토리 실패: 콘솔 에러, 빈 대화. 승인 요청 120초 무응답: 서버가 거부로 처리하고 도구 결과에 `denied` 가 온다. 음성 TTS 오류: `error` 로 와서 음성 상태가 풀린다.

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
| 리액터 캔버스(링·눈금·별), 입자 구 | `hud.js`, `sphere.js` | `HUD.state`, `BRAND.palette` | 가운데 |
| 음성(`VoiceManager`) | `voice.js`, `voice-ui.js` | 브라우저 Web Speech 또는 서버 STT/TTS | 구체, 입력 |
| 연결 배너, 드로어, 스크림 | `index.html`, `shell.js` | 연결 상태, 뷰포트 폭 | 전역 |
| 서비스 워커 | `sw.js` | 셸 파일 목록 | 오프라인 폴백. 셸은 네트워크 우선 |

---

## 미구현 / 알려진 제약

- 피드백 답은 완전 일치 키워드만 읽는다. "응 그걸로 해줘" 는 피드백이 아니라 보통 메시지다.
- Full-voice 승인 답도 키워드 판정이다. 모르는 말은 거부가 되므로 "그거 돌려" 같은 허용 의도도 거부된다. 모달 버튼은 그대로 쓸 수 있다.
- Full-voice 동안 마이크를 잡아 두므로 브라우저의 녹음 표시가 계속 켜져 있고, 블루투스 헤드셋은 통화 음질로 읽는다.
- Full-voice 의 자동 듣기는 읽기가 끝난 직후 한 번뿐이다. 말이 없으면 멈추고, 다시 시작하려면 구체를 누른다.
- 읽기가 겹치면(💬 filler 를 읽는 중에 승인 요청이 오면) 소리가 겹치고, 먼저 끝난 쪽에서 듣기가 시작될 수 있다.
- Focus 모드는 없다. 🔔 를 세션 단위로 끄려면 서버 쪽 게이팅이 필요하다.
- 세션 목록은 프로세스가 띄운 것만 보인다. 저장소에만 있는 세션은 화면에 없다.
- Postgres 저장소에서 ⑂ 분기는 빈 새 세션이다. 히스토리가 복사되지 않는다.
- open loop 중복 판정은 정규화 일치, 포함 관계(6자 이상), 글자 bigram 겹침(Jaccard 0.4 이상)이다. 단어를 통째로 바꾼 약속("참석자 목록" 과 "최종 리스트")은 따로 쌓인다.
- open loop 는 ✓ / ✕ 말고도, 대화에서 끝났거나 취소됐다고 사고가 판단하면 done 으로, 사용자가 취소하는 말로 가리키면 dismissed 로, 기한이 지나면 expired 로 저절로 닫혀 AGENDA 에서 빠진다. 잘못 닫힌 것을 되살리는 화면은 없다.
- 사용자 입력과 글자가 거의 겹치지 않는 새 약속은 저장하지 않는다. 입력과 전혀 다른 말로 바꿔 적은 약속은 AGENDA 에 오지 않는다.
- open loop 는 닫기만 되고 수정·되살리기는 없다. 스케줄은 켜고 끄기만 되고 만들기·지우기는 슬래시 명령(`/schedule`)으로.
- 음성 TTS 요청에 서버가 응답하지 않으면 `음성 처리 중` 상태에 머문다(서버가 빈 `voice_tts_audio` 를 돌려주는 것으로 막고 있다).
- 오른쪽 아티팩트 패널은 응답 하나에 코드블록 하나만 보여준다(가장 긴 것).
- 입력창은 한 줄이다. 줄바꿈 입력 없음.
- TUI 는 이 문서 범위 밖. 같은 백엔드를 쓰지만 화면 구성이 다르다.
