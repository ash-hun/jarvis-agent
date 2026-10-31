# JARVIS 기능 정의서

| 항목 | 값 |
|---|---|
| Last Updated | 2026-11-01 |

> `Last Updated` 는 문서 내용이 실제로 바뀐 날만 적는다. 시각은 적지 않는다.

---

## 서비스 개요

한 사용자를 위한 개인 비서 에이전트다. 터미널(TUI)과 브라우저(Web HUD)에서 같은 백엔드로 대화하고, 에이전트는 도구를 쓰고, 장기 기억과 약속(open loop)을 쌓고, 요청이 없어도 먼저 말을 건네고, 스케줄과 목표를 대화 밖에서 돌린다. 최상위 에이전트(JARVIS, 정의 파일로 더하는 KAREN 같은 에이전트)가 서로 일을 맡기고 묻는다.

범위 밖: 여러 사용자의 계정 관리, 모바일 앱 빌드 결과(`/m/`)의 소스는 이 저장소의 `src/` 에 없다.

---

## 기능 목록

기능 ID 알파벳순.

| 기능 ID | 기능 | 진입점 | 상태 |
|---|---|---|---|
| `agent_conversation` | 최상위 에이전트끼리 일을 맡기고 되묻는 대화 | `ask_agent` 도구 | 구현됨 |
| `agent_loop` | 한 턴의 LLM 호출과 도구 실행 반복 | ws `user_message`, TUI 입력창 | 구현됨 |
| `agent_registry` | 정의 파일로 최상위 에이전트를 더하고 화면 브랜드를 바꾼다 | `GET /api/agents`, `GET /brand.js`, `jarvis --agent <id>` | 구현됨 |
| `approval` | 위험한 도구 실행 전 사용자 승인과 "항상 허용" 규칙 | ws `approval_request` / `approval_response`, TUI 승인 모달 | 구현됨 |
| `external` | 캘린더, 메일 같은 외부 변화를 주기적으로 읽어 성찰에 먹인다 | `~/.jarvis/external_sources/*.yaml` | 구현됨 |
| `focus` | 한 작업을 네 sub-agent 의 도움으로 끝까지 수행하는 모드 | `/focus <작업>` (Web HUD) | 구현됨 |
| `goal` | 맡긴 목표를 대화 밖에서 한 단계씩 진행하고 알릴 것만 알린다 | `/goal`, `goal` 도구 | 구현됨 |
| `housing` | LH, SH 청약 공고 조회와 감시, 대출 원리금 계산 | `lh_notice`, `sh_notice`, `housing_budget`, `housing_loan`, `housing_profile`, `housing_watch` 도구, `/housing` | 구현됨 |
| `journal` | 사고 로그를 성찰해 저널로 남긴다 | `/journal` | 구현됨 |
| `mcp` | MCP 서버의 툴을 에이전트 도구로 등록 | 설정 `mcp_servers` | 구현됨 |
| `memory` | 범위를 아는 장기 기억과 작업 기억의 저장, 회상, 공고화 | `/remember`, `/compact`, `recall_episodes` 도구 | 구현됨 |
| `memory_eval` | 메모리 기능별 평가와 외부 벤치마크 실행 | `uv run python -m jarvis.memory.eval` | 구현됨 |
| `multi_agent` | 서브 에이전트를 패턴(supervisor, hierarchical, market, blackboard)으로 조율 | `/orchestrate`, `orchestrate` 도구 | 구현됨 |
| `notify` | 먼저 건넨 말과 스케줄 결과를 슬랙, 디스코드, Web Push 로도 보낸다 | `GET /api/push/vapid`, `PUT /api/push/subscriptions`, `DELETE /api/push/subscriptions`, ws `voice_spoken` | 구현됨 |
| `openloop` | 대화에서 흘린 약속과 미완 작업을 추적하는 AGENDA | `GET /api/agenda`, `POST /api/openloops/{loop_id}`, `/openloop` | 구현됨 |
| `plugins` | 턴과 도구 호출 앞뒤에 끼우는 플러그인 훅 | `~/.jarvis/plugins/*.py` | 구현됨 |
| `policy` | 입력 검증, 인증, 정책, 샌드박스 4단계 보안 파이프라인과 접근 키 | `/api/*`, `/ws` 의 `Authorization` 헤더 또는 `token` 쿼리 | 구현됨 |
| `proactive` | 요청 없이 성찰해 먼저 말을 건네고 반응으로 임계치를 학습 | ws `proactive_message`, `proactive_feedback`, TUI `ctrl+y` / `ctrl+g` | 구현됨 |
| `proactive_eval` | "먼저 말해야 했나" 사례로 proactive 정책을 잰다 | `uv run python -m jarvis.core.proactive.eval` | 구현됨 |
| `procedures` | 성공한 다단계 작업을 절차로 증류하고 승인된 절차를 도구와 스킬로 노출 | `/procedures` | 구현됨 |
| `scheduler` | cron 반복 작업과 한 번 실행 작업을 돌리고 결과를 알린다 | `/schedule`, `schedule` 도구, `POST /api/schedules/{name}`, ws `reminder` | 구현됨 |
| `session` | 세션 목록, 만들기, 분기, 삭제, 이력, 내보내기, 비용 보고, 옛 데이터 정리 | `GET /api/sessions`, `POST /api/sessions`, `POST /api/sessions/{session_id}/branch`, `DELETE /api/sessions/{session_id}`, `GET /api/sessions/{session_id}/messages`, `/sessions`, `/branch`, `/export`, `/cost`, `/cleanup` | 구현됨 |
| `skills` | Markdown/YAML 명령 매크로를 `/스킬 인자` 로 펼친다 | `/<스킬 이름> <인자>`, `~/.jarvis/skills/*.md` | 구현됨 |
| `task_pattern` | 사용자가 알려 준 일하는 방식을 그 에이전트만 기억한다 | `remember_task_pattern` 도구, `/patterns` | 구현됨 |
| `thought` | 요청 시점과 성찰 시점의 inner thought, router 판정, 짧은 답 분류 | ws `inner_thought`, `thought_route`, `thought_end`, `reply_classify` | 구현됨 |
| `tools` | 파일, 셸, 검색, 웹 내장 도구와 파일 기반 사용자 도구 | `GET /api/tools`, `/tools`, `~/.jarvis/tools/` | 구현됨 |
| `tui` | Textual 터미널 화면 | `jarvis`, `jarvis --session <id>`, `jarvis --list-sessions` | 구현됨 |
| `usermodel` | 누적 기억에서 사용자 모델을 증류한다 | `/usermodel` | 구현됨 |
| `voice` | 서버와 브라우저 STT/TTS, 읽기 문구, "Jarvis" 웨이크워드 | ws `voice_tts_request`, `voice_stt_submit`, 바이너리 프레임, `GET /api/voice/phrases/{name}`, TUI `ctrl+t` / `ctrl+r` | 구현됨 |
| `web_hud` | 브라우저 HUD 화면 셸과 FastAPI 앱 기동 | `jarvis --web`, `/` 화면 | 구현됨 |

---

## 기능별 상세

### agent_conversation: 최상위 에이전트 간 대화

**설명**: 최상위 에이전트가 다른 최상위 에이전트에게 일을 맡기거나 물어보고, 에이전트 쌍마다 이어지는 대화 세션에서 답을 받는다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `ask_agent` 도구 호출(받는 에이전트, 질문) | 받는 쪽의 `peer-<부른 쪽>-<받는 쪽>` 세션에서 한 턴을 돌린 답. Web HUD 에서는 그 세션이 세션 목록에 열린다 |

**처리 흐름**: `agent_conversation.AskAgentTool` 에서 받을 수 있는 질문 규칙과 깊이 제한을 확인하고, 쌍 세션을 열어(Web 은 `WebState.open_peer_session`, TUI 와 스케줄은 `AgentRegistry.open_peer_session`) 받는 쪽 `AgentSession.prompt` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/app/agent_conversation.py` | app | `ask_agent` 도구와 에이전트 쌍 대화 세션 규칙 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_agent_conversation_agent_conversation.py` |
| 통합 | `tests/integ/test_agent_conversation.py` |

**제약과 미구현**: 에이전트끼리의 대화 세션은 Web HUD 세션 목록에 다른 세션처럼 보인다(`docs/view_spec.md`).

---

### agent_loop: 에이전트 턴 실행

**설명**: 사용자 입력 하나에 대해 LLM 호출과 도구 실행을 `max_turns` 안에서 반복하고, 스트리밍 이벤트를 화면에 보낸다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| ws `user_message{text}`, TUI 입력 | `agent_start`, `message_update`, `tool_execution_start`, `tool_execution_end`, `agent_end` 이벤트와 세션에 저장된 메시지 |
| ws `abort`, `ctrl+k` | 진행 중인 루프 중단 |

**처리 흐름**: `ws_router` 에서 `AgentSession.prompt` 로, 보안 파이프라인, 스킬 확장, router 판정, 사고와 AGENDA 판단 띄우기, `AgentHarness.run`, `run_agent_loop`, `model_layer.stream`, 도구 실행기 순. 프로바이더나 저장소가 예외를 던져도 `AgentHarness.run` 이 `finally` 에서 실행 표시(`is_running`)를 풀어, 다음 턴이 실행 중으로 막히지 않는다.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/loop.py` | agent_layer | LLM 호출과 툴 실행을 반복하는 루프 본체 |
| `src/jarvis/agent_layer/harness.py` | agent_layer | 세션 이력, 작업 기억 변환, 이벤트 구독을 묶어 한 턴을 돌리는 래퍼 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_agent_loop_agent_types.py` |
| 단위 | `tests/unit/test_agent_loop_anthropic.py` |
| 단위 | `tests/unit/test_agent_loop_gemini.py` |
| 단위 | `tests/unit/test_agent_loop_harness.py` |
| 단위 | `tests/unit/test_agent_loop_loop.py` |
| 단위 | `tests/unit/test_agent_loop_model_registry.py` |
| 단위 | `tests/unit/test_agent_loop_model_types.py` |
| 단위 | `tests/unit/test_agent_loop_ollama.py` |
| 단위 | `tests/unit/test_agent_loop_openai.py` |
| 단위 | `tests/unit/test_agent_loop_provider_base.py` |
| 단위 | `tests/unit/test_agent_loop_session.py` |
| 단위 | `tests/unit/test_agent_loop_stream.py` |
| 단위 | `tests/unit/test_agent_loop_vllm.py` |
| 통합 | 없음. 턴 루프는 `tests/integ/test_web_hud.py` 의 ws 턴 시나리오가 함께 돈다 |

**제약과 미구현**: 메인 모델의 프롬프트 처리 시간이 첫 글자 지연의 대부분이라 시스템 프롬프트와 도구 목록 크기를 줄이는 일이 남아 있다(`TODO.md`).

---

### agent_registry: 최상위 에이전트 등록

**설명**: `~/.jarvis/team/*.yaml` 정의 파일 한 장이 최상위 에이전트 하나가 된다. 에이전트마다 이름, 명언, 색, 모델, 개성, 도구 목록, 도구 경계(`ask`, `never`), 층별 기억 읽기 정책(`memory.read`)을 갖고, 비운 항목은 main 설정을 이어받는다. Web HUD 는 세션 에이전트의 브랜드로 칠해진다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `GET /api/agents` | 최상위 에이전트 목록(main 먼저) |
| `GET /brand.js`, `GET /manifest.json` | main 에이전트의 워드마크, 명언, 색 |
| ws `?agent=<id>`, `jarvis --agent <id>` | 그 에이전트가 맡는 새 세션. 모르는 에이전트면 ws 는 `4404` |
| 루프 시작, 끝 | ws `agent_activity{active[]}` |

**처리 흐름**: `agent_registry` 가 정의 파일을 읽어 에이전트마다 `AgentProfile` 과 `SessionBuilder` 를 들고, `agent_router` 와 `brand_router` 가 화면에 내주고, `agent_activity` 가 일하는 에이전트 변화를 방송하는 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/app/agent_registry.py` | app | 정의 파일을 읽어 에이전트별 프로필과 세션 빌더를 드는 레지스트리 |
| `src/jarvis/ui/web/router/agent_router.py` | ui | `GET /api/agents` |
| `src/jarvis/ui/web/router/brand_router.py` | ui | `GET /brand.js`, `GET /manifest.json` 브랜드 주입 |
| `src/jarvis/ui/web/agent_activity.py` | ui | 일하는 에이전트 집계와 `agent_activity` 방송 |
| `src/jarvis/ui/web/static/app/agents.js` | ui | 에이전트 칩, 세션 표식 색, AGENDA 라벨 |
| `src/jarvis/ui/web/static/app/brand.js` | ui | 세션 에이전트의 이름, 명언, 색 적용 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_agent_registry_agent_activity.py` |
| 단위 | `tests/unit/test_agent_registry_agent_profile.py` |
| 단위 | `tests/unit/test_agent_registry_agent_registry.py` |
| 단위 | `tests/unit/test_agent_registry_brand_router.py` |
| 단위 | `tests/unit/test_agent_registry_infra_builder.py` |
| 통합 | `tests/integ/test_agent_registry.py` |

**제약과 미구현**: 구체 색 섞기는 두 색까지다. AGENDA 에 에이전트별 필터가 없다(`docs/view_spec.md`).

---

### approval: 도구 실행 승인

**설명**: 승인이 필요한 도구를 실행하기 전에 사용자에게 묻고, "항상 허용"한 (도구, 패턴)은 에이전트별 규칙 파일에 남겨 다시 묻지 않는다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 승인 필요 도구 호출 | ws `approval_request{id, command, reason, always_pattern}` 을 세션의 연결 전부에 보낸다 |
| ws `approval_response{id, approved, always}` | 먼저 온 답 하나만 채택, `approval_resolved`. `always=true` 면 `approvals/<agent_id>.yaml` 에 패턴 저장 |
| 120초 무응답 | 거부로 처리, `approval_resolved{timeout:true}` |

**처리 흐름**: 도구 실행기에서 `sandbox.authorize` 로, `approval_rules` 대조, `SessionApprovals` 가 연결 전부에 요청, 첫 답 채택, `approval_rules` 저장 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/policy/approval_rules.py` | core | "항상 허용" 규칙 YAML 저장과 대조 |
| `src/jarvis/ui/web/approvals.py` | ui | 세션 하나의 승인 요청을 연결 전부에 보내고 먼저 온 답을 쓴다 |
| `src/jarvis/ui/tui/components/approval_dialog.py` | ui | TUI 승인 모달 |
| `src/jarvis/ui/web/static/app/approval.js` | ui | 승인 모달과 음성 답 해석(`parseApprovalAnswer`) |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_approval_approval_rules.py` |
| 단위 | `tests/unit/test_approval_approvals.py` |
| 통합 | `tests/integ/test_approval.py` |

**제약과 미구현**: 음성 승인 답에 부정어가 있으면 분류 없이 거부한다. 에어팟에서 승인 되읽기가 들리는지 실기기 확인 전이다(`TODO.md`).

---

### external: 외부 트리거

**설명**: 선언한 외부 소스(MCP 서버의 툴)를 소스별 주기로 훑어 새 사실만 inbox 에 쌓고 성찰을 깨워, 에이전트가 외부 변화를 근거로 먼저 말하게 한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `~/.jarvis/external_sources/*.yaml` | 소스별 주기 폴링, 이미 본 이벤트는 `~/.jarvis/external_seen.jsonl` 로 걸러 재발화 없음 |
| 새 외부 이벤트 | 성찰 트리거가 깨어나고 세션이 inbox 를 한 번 비워 사고 요청에 싣는다 |

**처리 흐름**: `external_loader` 에서 `poller` 로, `mcp_source.poll`, `dedup`, `inbox` 적재, `ExternalTrigger` 깨우기, `AgentSession.reflect` 의 `_drain_external_events` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/external/external_loader.py` | core | 외부 소스 YAML 을 `ExternalSourceSpec` 목록으로 |
| `src/jarvis/core/external/external_protocol.py` | core | 외부 소스 기본 클래스 |
| `src/jarvis/core/external/external_types.py` | core | 외부 사실 1건의 모델 |
| `src/jarvis/core/external/mcp_source.py` | core | MCP 툴 원문을 외부 이벤트로 바꾸는 소스 |
| `src/jarvis/core/external/dedup.py` | core | 원문을 이벤트로 쪼개고 이미 본 것을 거른다 |
| `src/jarvis/core/external/inbox.py` | core | 앱 레벨 외부 이벤트 큐 |
| `src/jarvis/core/external/poller.py` | core | 소스별 주기 폴링과 성찰 트리거 깨우기 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_external_dedup.py` |
| 단위 | `tests/unit/test_external_external_loader.py` |
| 단위 | `tests/unit/test_external_external_protocol.py` |
| 단위 | `tests/unit/test_external_external_types.py` |
| 단위 | `tests/unit/test_external_inbox.py` |
| 단위 | `tests/unit/test_external_mcp_source.py` |
| 단위 | `tests/unit/test_external_poller.py` |
| 통합 | `tests/integ/test_external.py` |

**제약과 미구현**: 없음.

---

### focus: Focus 모드

**설명**: 세션마다 작업 하나를 열고, 매 턴 분석, 기록, 진행, 조사 sub-agent 를 돌려 Web HUD 의 네 영역(REFERENCE, LOG, ANALYSIS, PROGRESS)을 채우고 메인 에이전트의 시스템 프롬프트에 작업 맥락을 붙인다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/focus <작업>`, 음성 "포커스 모드 <작업>" | 작업 시작, 첫 분석과 단계 계획을 `JARVIS_FOCUS__READY_TIMEOUT_SEC` 까지 기다린 뒤 작업 문장으로 첫 응답. 이미 작업이 있으면 거절 |
| `/focus stop` (`off`, `종료`) | 종료, `focus_state{active:false}`. 두 번째부터는 아무것도 하지 않음 |
| `/focus` | 진행률과 단계 텍스트 |
| 매 턴 | `focus_panel{area, markdown, busy}`, `focus_state{state}` |

**처리 흐름**: `ws_router` 가 디스패처보다 먼저 `focus_types` 로 명령을 해석하고 `FocusService.handle` 로, `focus_store` 의 활성 표시 배타 생성, `prompts` 로 sub-agent 지시문 조립, 턴 훅(`before_turn`, `after_turn`)에서 sub-agent 실행, `focus_panel` / `focus_state` 전송 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/focus/focus_service.py` | core | 세션별 작업 열고 닫기, 턴마다 sub-agent 넷 실행과 화면 전송 |
| `src/jarvis/core/focus/focus_store.py` | core | `~/.jarvis/focus/` 파일 기록과 세션당 활성 작업 하나 보증 |
| `src/jarvis/core/focus/focus_types.py` | core | 상태, 진행률, 예상 시간, 명령 해석 순수 함수 |
| `src/jarvis/core/focus/prompts.py` | core | sub-agent 역할 지시문과 메인 에이전트 맥락 조립 |
| `src/jarvis/ui/web/static/app/focus.js` | ui | Focus 레이아웃과 네 영역 렌더, 음성 키워드 해석 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_focus_focus_service.py` |
| 단위 | `tests/unit/test_focus_focus_store.py` |
| 단위 | `tests/unit/test_focus_focus_types.py` |
| 통합 | `tests/integ/test_focus.py` |

**제약과 미구현**: Web HUD 에서만 쓸 수 있다(TUI 에서는 안내만 돌려준다). Focus 동안 🔔 는 보내지 않는다. 분석 결과는 이번 응답이 아니라 다음 응답에 들어간다(첫 지시만 기다린다).

---

### goal: 목표

**설명**: 대화 중에 맡긴 목표를 기록하고 스케줄러에 차례를 걸어, 대화 밖에서 에이전트가 한 단계씩 진행하고 새로 알릴 것만 알린다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/goal <문장>`, `goal` 도구(맡기기) | `~/.jarvis/goals/<id>.json` 저장, 스케줄 `goal-<목표 id>` 등록. 같은 목표는 하나 |
| `/goal` | 목표 목록 |
| `/goal stop <문장>` | 그 목표의 차례를 멈춘다 |
| 차례마다 | 새로 알릴 항목이 있을 때만 ws `reminder{kind:"goal", label:"목표: ..."}` |

**처리 흐름**: `goal_cmd` 또는 `GoalTool` 에서 `goals_store` 저장과 `SchedulerService` 등록으로, 차례마다 `runner` 가 프롬프트를 짓고 경계 안의 도구로 에이전트를 돌려 `goals_types` 로 답을 읽고 알릴 항목을 고르는 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/goals/goals_store.py` | core | id 마다 JSON 파일 하나인 목표 저장소 |
| `src/jarvis/core/goals/goals_types.py` | core | 목표 모델, 자연 키, 답 해석, 알릴 항목 고르기 |
| `src/jarvis/core/goals/runner.py` | core | 목표 한 차례 실행 |
| `src/jarvis/core/goals/tool.py` | core | `goal` 도구(맡기기, 목록, 멈추기) |
| `src/jarvis/core/slash/goal_cmd.py` | core | `/goal` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_goal_goal_cmd.py` |
| 단위 | `tests/unit/test_goal_goals_store.py` |
| 단위 | `tests/unit/test_goal_goals_types.py` |
| 단위 | `tests/unit/test_goal_runner.py` |
| 단위 | `tests/unit/test_goal_tool.py` |
| 통합 | 없음. 스케줄러 차례부터 알림까지 잇는 시나리오가 아직 없다 |

**제약과 미구현**: 알린 직후 정산 전에 죽으면 다음 차례에 같은 항목을 한 번 더 알린다(`# idempotent`). 결과가 바뀐 차례는 도구를 두 번 부른다(`# ponytail`).

---

### housing: 청약 공고와 대출 계산

**설명**: 정의에 이 도구 이름을 적은 에이전트(KAREN)가 LH, SH 공고를 조회, 감시하고, 사용자의 주거 프로필로 공고마다 대출 경우의 수와 월 부담을 계산한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `lh_notice`, `sh_notice` 도구 | 조건에 맞는 공고 목록과 KST 기준 마감, 상세 본문과 첨부 |
| `housing_budget` 도구(현금, 월 여유자금) | 열린 공고마다 대출 상품, 규제지역, 보증금 전환, 현금 투입 경우별 월 부담. 추천한 공고의 마감 전 약속을 open loop 로 남긴다 |
| `housing_loan` 도구 | 상환 방식별 월, 연간 원리금과 이자, 금리 역산 |
| `housing_profile` 도구, `/housing set 항목=값`, `/housing clear` | 주거 프로필 조회, 변경, 삭제 |
| `housing_watch` 도구 | 지난 조회 뒤 새 공고 중 신청 가능성이 있는 것만 한 번 알림 |

**처리 흐름**: `budget` 에서 `lh_notice` / `sh_notice` 조회로, `fetch`, `markup`, `notice_pdf` / `sh_terms` / `rental_complex` 금액 읽기, `profile` 과 `rules` 로 자격과 한도, `scenario` 경우 펼치기, `deadline` 약속 남기기 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/tools/housing/amount.py` | core | 한국어 금액을 원 단위 정수로 |
| `src/jarvis/core/tools/housing/budget.py` | core | `housing_budget` 도구 |
| `src/jarvis/core/tools/housing/deadline.py` | core | 추천 공고 마감 전 open loop |
| `src/jarvis/core/tools/housing/fetch.py` | core | 게시판 HTML 과 첨부를 가져오는 HTTP 경계, KST 오늘 |
| `src/jarvis/core/tools/housing/lh_notice.py` | core | `lh_notice` 도구 |
| `src/jarvis/core/tools/housing/loan.py` | core | `housing_loan` 도구 |
| `src/jarvis/core/tools/housing/loan_rules.yaml` | core | 대출 상품과 규제 규칙 데이터 |
| `src/jarvis/core/tools/housing/markup.py` | core | 게시판 HTML 에서 텍스트, 표, 날짜 추출 |
| `src/jarvis/core/tools/housing/notice_pdf.py` | core | LH 공고문 PDF 의 임대조건과 분양가 표 읽기 |
| `src/jarvis/core/tools/housing/profile.py` | core | 주거 조건 모델과 변경 규칙 |
| `src/jarvis/core/tools/housing/profile_tool.py` | core | `housing_profile` 도구 |
| `src/jarvis/core/tools/housing/rental_complex.py` | core | LH 임대주택 단지 금액 읽기와 공고 제목 맞추기 |
| `src/jarvis/core/tools/housing/rules.py` | core | 자격, 금리, 대출 한도 결정 |
| `src/jarvis/core/tools/housing/scenario.py` | core | 주택형 하나의 월 부담 경우 펼치기 |
| `src/jarvis/core/tools/housing/sh_notice.py` | core | `sh_notice` 도구 |
| `src/jarvis/core/tools/housing/sh_terms.py` | core | SH 모집 공고 고르기와 공고문 금액 읽기 |
| `src/jarvis/core/tools/housing/watch.py` | core | `housing_watch` 도구 |
| `src/jarvis/core/slash/housing_cmd.py` | core | `/housing` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_housing_amount.py` |
| 단위 | `tests/unit/test_housing_budget.py` |
| 단위 | `tests/unit/test_housing_deadline.py` |
| 단위 | `tests/unit/test_housing_fetch.py` |
| 단위 | `tests/unit/test_housing_housing_cmd.py` |
| 단위 | `tests/unit/test_housing_lh_notice.py` |
| 단위 | `tests/unit/test_housing_loan.py` |
| 단위 | `tests/unit/test_housing_markup.py` |
| 단위 | `tests/unit/test_housing_notice_pdf.py` |
| 단위 | `tests/unit/test_housing_profile.py` |
| 단위 | `tests/unit/test_housing_profile_tool.py` |
| 단위 | `tests/unit/test_housing_rental_complex.py` |
| 단위 | `tests/unit/test_housing_rules.py` |
| 단위 | `tests/unit/test_housing_scenario.py` |
| 단위 | `tests/unit/test_housing_sh_notice.py` |
| 단위 | `tests/unit/test_housing_sh_terms.py` |
| 단위 | `tests/unit/test_housing_watch.py` |
| 통합 | `tests/integ/test_housing.py` |

**제약과 미구현**: 공고 상세는 100건, 공고문 PDF 는 한 번에 60건까지만 연다. LH 전체 조회는 `MAX_PAGES` 쪽까지, `housing_watch` 는 게시판마다 첫 쪽(최신 10건)만 본다. SH 는 최근 `RECENT_DAYS` 안의 모집 글 `MAX_NOTICES` 건만 본다. 소득 기준은 1인 기준만 댄다. 단위 없는 '천'은 천만으로 읽는다. `housing_watch` 는 알리기 전에 본 것으로 적어 알림이 실패하면 그 공고는 다시 오지 않는다(모두 `# ponytail`).

---

### journal: 자기 성찰 저널

**설명**: 장기 기억에 쌓인 최근 사고 로그를 LLM 으로 성찰해 저널 항목(`source=journal`)으로 남기고 보여 준다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/journal` | 최근 저널 |
| `/journal write` | 새 저널 항목 작성 |

**처리 흐름**: `journal_cmd` 에서 `ReflectionJournaler` 로, `MemoryService` 의 사고 로그 조회, LLM 성찰, 저널 항목 저장 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/journal/journaler.py` | agent_layer | 사고 로그 성찰과 저널 항목 저장 |
| `src/jarvis/core/slash/journal_cmd.py` | core | `/journal` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_journal_journal_cmd.py` |
| 단위 | `tests/unit/test_journal_journaler.py` |
| 통합 | 없음. 실제 저장소에 사고 로그를 쌓아 저널을 쓰는 시나리오가 아직 없다 |

**제약과 미구현**: 사고(`thought.enabled`)가 꺼져 있으면 `/journal` 이 등록되지 않는다.

---

### mcp: MCP 도구

**설명**: 설정한 MCP 서버의 툴을 열거해 `JarvisTool` 로 감싸 도구 레지스트리에 등록하고 호출을 중계한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 설정 `mcp_servers` | 서버마다 툴이 에이전트 도구로 보인다 |
| 에이전트의 MCP 툴 호출 | MCP 서버 응답을 도구 결과로 |

**처리 흐름**: `InfraBuilder` 에서 `MCPToolLoader` 로, 서버 연결, 툴 열거, `MCPToolWrapper` 등록, 호출 중계 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/tools/mcp_loader.py` | core | MCP 툴 열거, 래핑, 등록, 호출 중계 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_mcp_mcp_loader.py` |
| 통합 | `tests/integ/test_mcp.py` |

**제약과 미구현**: 없음.

---

### memory: 에이전트 메모리

**설명**: (사용자, 에이전트, 세션) 범위를 아는 장기 기억(일화, 의미, 절차)과 세션 작업 기억(STM 최근 턴 창)을 두고, 턴 전 회상, 쓰기, 조용할 때의 공고화를 맡는다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 매 턴 | 범위 규칙과 합성 점수로 고른 기억을 프롬프트에 싣고, 턴 일화(EDM)를 남긴다 |
| `/remember <내용>`, `/remember list`, `/remember search <키워드>`, `/remember forget <id>` | 장기 기억 저장, 나열, 검색, 삭제 |
| `/compact` | 현재 세션을 요약해 장기 기억에 저장 |
| `recall_episodes` 도구 | 부른 에이전트의 지난 턴 일화를 작업 종류, 성패, 기간으로 회상 |
| 사용자가 조용할 때 | daemon 틱에 얹혀 활성 세션의 일화에서 "주제: 값" 사실 추출, 같은 작업 종류의 성공 턴 일화가 3번 쌓이면 절차 초안 정제(`procedures`) |

**처리 흐름**: `MemoryService.observe` 에서 `working.window` 와 `deixis` 로 창과 지칭을 정하고, `scope` 와 `access` 로 읽을 범위를 계산해 `stores` 조회, `retrieval.scoring` 과 `cues` 로 순위, `remember` 쓰기는 `long_term` 정책 적용, 공고화는 `consolidation.idle` 에서 `semantic_extract` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/memory/memory_service.py` | memory | observe, recall, recent, remember, 공고화 |
| `src/jarvis/memory/memory_types.py` | memory | 기억 종류와 항목 모델 |
| `src/jarvis/memory/scope.py` | memory | 메모리 범위와 읽기 상속 규칙 |
| `src/jarvis/memory/access.py` | memory | 에이전트별 층 읽기 정책 |
| `src/jarvis/memory/consolidation/compaction.py` | memory | 메시지 묶음 요약기(`/compact`) |
| `src/jarvis/memory/consolidation/idle.py` | memory | 유휴 공고화 |
| `src/jarvis/memory/consolidation/semantic_extract.py` | memory | 일화에서 사실 추출 |
| `src/jarvis/memory/long_term/episodic.py` | memory | 일화 기억 정책 |
| `src/jarvis/memory/long_term/semantic.py` | memory | 의미 기억 대체와 간섭 후보 |
| `src/jarvis/memory/long_term/procedural.py` | memory | 스킬 파일을 읽기 전용 절차 기억으로 노출 |
| `src/jarvis/memory/retrieval/cues.py` | memory | 단서 겹침 점수 |
| `src/jarvis/memory/retrieval/scoring.py` | memory | recency, importance, relevance 합성 점수 |
| `src/jarvis/memory/stores/store_protocol.py` | memory | 장기 기억 저장소 기본 클래스 |
| `src/jarvis/memory/stores/in_memory.py` | memory | 프로세스 메모리 저장소 |
| `src/jarvis/memory/stores/postgres.py` | memory | PostgreSQL 장기 기억 저장소 |
| `src/jarvis/memory/working/state.py` | memory | 작업 기억 상태와 저장소 기본 클래스 |
| `src/jarvis/memory/working/window.py` | memory | 최근 턴 창(tool 짝 보존) |
| `src/jarvis/memory/working/deixis.py` | memory | 상대 지칭 해석 |
| `src/jarvis/memory/working/in_memory.py` | memory | 작업 기억 메모리 저장소 |
| `src/jarvis/memory/working/postgres.py` | memory | 작업 기억 PostgreSQL 저장소 |
| `src/jarvis/core/tools/episodes.py` | core | `recall_episodes` 도구 |
| `src/jarvis/core/slash/remember_cmd.py` | core | `/remember` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_memory_access.py` |
| 단위 | `tests/unit/test_memory_compaction.py` |
| 단위 | `tests/unit/test_memory_cues.py` |
| 단위 | `tests/unit/test_memory_deixis.py` |
| 단위 | `tests/unit/test_memory_embeddings.py` |
| 단위 | `tests/unit/test_memory_episodes.py` |
| 단위 | `tests/unit/test_memory_episodic.py` |
| 단위 | `tests/unit/test_memory_idle.py` |
| 단위 | `tests/unit/test_memory_memory_service.py` |
| 단위 | `tests/unit/test_memory_memory_types.py` |
| 단위 | `tests/unit/test_memory_ops_cmd.py` |
| 단위 | `tests/unit/test_memory_procedural.py` |
| 단위 | `tests/unit/test_memory_remember_cmd.py` |
| 단위 | `tests/unit/test_memory_scope.py` |
| 단위 | `tests/unit/test_memory_scoring.py` |
| 단위 | `tests/unit/test_memory_semantic.py` |
| 단위 | `tests/unit/test_memory_semantic_extract.py` |
| 단위 | `tests/unit/test_memory_state.py` |
| 단위 | `tests/unit/test_memory_store_protocol.py` |
| 단위 | `tests/unit/test_memory_window.py` |
| 통합 | `tests/integ/test_memory.py` |

**제약과 미구현**: 항목 낱말이 답에 절반 넘게 나와야 쓰였다고 본다. 이력이 줄어 턴 번호를 다시 세면 옛 턴 일화를 덮는다. 조사 목록 휴리스틱으로 명사를 자른다. main 에이전트는 정의 파일이 없어 기본 정책(자기 것만)이다(모두 `# ponytail`).

---

### memory_eval: 메모리 평가

**설명**: jsonl 사례를 in-memory 대상에 넣고 질의해 기능별 지표를 내고, LongMemEval, LoCoMo 원본으로 증거 재현율을 잰다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `uv run python -m jarvis.memory.eval [--suite S] [--summarizer extractive\|llm] [--judge llm\|contains] [--json] [-v]` | 스위트별 지표 |
| `--benchmark longmemeval\|locomo --path <json> [--limit] [--seed] [--k] [--mode raw\|turns] [--extract llm] [--embedder fake\|config] [--judge llm\|contains]` | 외부 벤치마크 재현율과 정답 판정 |

**처리 흐름**: `__main__` 에서 `eval_schema` 로 사례 로드, `runner` 가 사례마다 저장소를 비우고 `target` 에 재생, `metrics` 집계 순. 벤치마크는 `adapters` 에서 `benchmark` 로, 선택적으로 `judge`, `probe` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/memory/eval/__main__.py` | memory | 평가 CLI |
| `src/jarvis/memory/eval/eval_schema.py` | memory | 사례 형식과 로더 |
| `src/jarvis/memory/eval/runner.py` | memory | 사례 재생과 판정 |
| `src/jarvis/memory/eval/target.py` | memory | 평가 대상 어댑터 |
| `src/jarvis/memory/eval/metrics.py` | memory | 판정과 스위트별 집계 |
| `src/jarvis/memory/eval/faithfulness.py` | memory | 요약 뒤 사실 보존율 |
| `src/jarvis/memory/eval/fake_embedder.py` | memory | 결정론 임베더 |
| `src/jarvis/memory/eval/benchmark.py` | memory | 외부 벤치마크 실행 |
| `src/jarvis/memory/eval/judge.py` | memory | 회상 증거로 답 생성과 정답 판정 |
| `src/jarvis/memory/eval/probe.py` | memory | LLM 호출 횟수 계측 |
| `src/jarvis/memory/eval/adapters/locomo.py` | memory | LoCoMo 어댑터 |
| `src/jarvis/memory/eval/adapters/longmemeval.py` | memory | LongMemEval 어댑터 |
| `src/jarvis/memory/eval/datasets/` | memory | 기능별 평가 사례 jsonl |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_memory_eval_benchmark.py` |
| 단위 | `tests/unit/test_memory_eval_faithfulness.py` |
| 단위 | `tests/unit/test_memory_eval_judge.py` |
| 단위 | `tests/unit/test_memory_eval_locomo.py` |
| 단위 | `tests/unit/test_memory_eval_longmemeval.py` |
| 단위 | `tests/unit/test_memory_eval_metrics.py` |
| 단위 | `tests/unit/test_memory_eval_probe.py` |
| 단위 | `tests/unit/test_memory_eval_runner.py` |
| 단위 | `tests/unit/test_memory_eval_target.py` |
| 통합 | 없음. 평가 도구 자체라 CLI 를 끝까지 돌리는 테스트를 두지 않았다 |

**제약과 미구현**: 벤치마크 원본 데이터는 레포 밖에 둔다.

---

### multi_agent: 멀티 에이전트 오케스트레이션

**설명**: `~/.jarvis/agents/*.yaml` 서브 에이전트를 노드로 감싸 supervisor, hierarchical, market, blackboard 패턴(과 그 파이프라인 합성)으로 일을 나눠 맡긴다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/orchestrate <pattern> [--agents a,b] [--promote] <작업>` | 지정한 패턴으로 서브 에이전트를 조율한 결과 |
| `orchestrate` 도구 | 메인 LLM 이 고른 패턴과 참여 에이전트로 실행 |
| 서브 에이전트 위임 도구(`AgentNodeTool`) | LLM 이 tool_call 로 서브 에이전트 하나에 위임 |

**처리 흐름**: `orchestrate_cmd` 또는 `orchestrate_tool` 에서 `OrchestrationService` 로, `multi_agent_loader` 정의, `factory` 가 부모 범위를 물려받은 자식 세션 노드 생성, 토폴로지 조립, 오케스트레이터 dispatch, `blackboard` 와 작업 공유 메모리로 결과 전달 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/multi_agent/multi_agent_service.py` | core | 패턴 이름과 작업으로 조립해 실행하는 공통 뒷단 |
| `src/jarvis/core/multi_agent/multi_agent_loader.py` | core | 에이전트 YAML 을 `AgentDefinition` 으로 |
| `src/jarvis/core/multi_agent/multi_agent_protocol.py` | core | 노드, 토폴로지, 오케스트레이터 기반 클래스 |
| `src/jarvis/core/multi_agent/factory.py` | core | 격리된 자식 세션 노드 생성과 `memory.stm` 수명 관리 |
| `src/jarvis/core/multi_agent/node.py` | core | `AgentNode`, `LazyAgentNode` |
| `src/jarvis/core/multi_agent/task.py` | core | 같은 입력이면 같은 `task_id` 인 `AgentTask`, `AgentResult` |
| `src/jarvis/core/multi_agent/tool.py` | core | `AgentNodeTool` |
| `src/jarvis/core/multi_agent/orchestrate_tool.py` | core | `orchestrate` 도구 |
| `src/jarvis/core/multi_agent/blackboard.py` | core | 공유 블랙보드 저장소 |
| `src/jarvis/core/multi_agent/orchestrators/orchestrator_base.py` | core | 오케스트레이터 공통 동작 |
| `src/jarvis/core/multi_agent/orchestrators/supervisor.py` | core | supervisor 오케스트레이터 |
| `src/jarvis/core/multi_agent/orchestrators/hierarchical.py` | core | hierarchical 오케스트레이터 |
| `src/jarvis/core/multi_agent/orchestrators/market.py` | core | market 오케스트레이터 |
| `src/jarvis/core/multi_agent/orchestrators/blackboard.py` | core | blackboard 오케스트레이터 |
| `src/jarvis/core/multi_agent/orchestrators/pipeline.py` | core | 오케스트레이터 순차 합성 |
| `src/jarvis/core/multi_agent/topologies/topology_base.py` | core | 토폴로지 공통 노드 관리 |
| `src/jarvis/core/multi_agent/topologies/supervisor.py` | core | 1:N flat 토폴로지 |
| `src/jarvis/core/multi_agent/topologies/hierarchical.py` | core | 레벨 트리 토폴로지 |
| `src/jarvis/core/multi_agent/topologies/p2p.py` | core | full-mesh P2P 토폴로지 |
| `src/jarvis/core/multi_agent/topologies/blackboard.py` | core | 블랙보드 토폴로지 |
| `src/jarvis/core/slash/orchestrate_cmd.py` | core | `/orchestrate` 핸들러 |
| `src/jarvis/app/subagent_builder.py` | app | 서브 에이전트 세션과 위임 도구 조립 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_multi_agent_blackboard.py` |
| 단위 | `tests/unit/test_multi_agent_factory.py` |
| 단위 | `tests/unit/test_multi_agent_market.py` |
| 단위 | `tests/unit/test_multi_agent_multi_agent_loader.py` |
| 단위 | `tests/unit/test_multi_agent_multi_agent_protocol.py` |
| 단위 | `tests/unit/test_multi_agent_multi_agent_service.py` |
| 단위 | `tests/unit/test_multi_agent_node.py` |
| 단위 | `tests/unit/test_multi_agent_orchestrate_cmd.py` |
| 단위 | `tests/unit/test_multi_agent_orchestrator_base.py` |
| 단위 | `tests/unit/test_multi_agent_orchestrators_blackboard.py` |
| 단위 | `tests/unit/test_multi_agent_orchestrators_hierarchical.py` |
| 단위 | `tests/unit/test_multi_agent_p2p.py` |
| 단위 | `tests/unit/test_multi_agent_pipeline.py` |
| 단위 | `tests/unit/test_multi_agent_subagent_builder.py` |
| 단위 | `tests/unit/test_multi_agent_task.py` |
| 단위 | `tests/unit/test_multi_agent_tool.py` |
| 단위 | `tests/unit/test_multi_agent_topologies_hierarchical.py` |
| 단위 | `tests/unit/test_multi_agent_topology_base.py` |
| 통합 | `tests/integ/test_multi_agent.py` |

**제약과 미구현**: 서브 에이전트가 하나도 없으면 `/orchestrate` 와 `orchestrate` 도구가 등록되지 않는다.

---

### notify: 외부 알림

**설명**: 먼저 건넨 말, 스케줄 결과, 화면이 소리 내어 읽은 말을 열린 화면 밖(슬랙, 디스코드 글 또는 음성 채널, iOS 홈 화면 웹앱 Web Push)으로도 보낸다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `proactive_message`, `reminder` 이벤트 | 설정된 채널마다 한 번 전송 |
| ws `voice_tts_request{source}`, `voice_spoken{phrase}` | 읽은 글을 `spoken` 으로 전송. 같은 세션의 같은 글은 10초 안에 한 번 |
| `GET /api/push/vapid` | VAPID 공개키 |
| `PUT /api/push/subscriptions`, `DELETE /api/push/subscriptions` | 구독 등록(endpoint 로 upsert), 해제 |

**처리 흐름**: `events` 에서 보낼 것만 골라 payload 로, `dedupe` 로 잠깐 사이 중복 제거, `slack`, `discord` 또는 `discord_voice`, `webpush` 로 fan out 하는 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/notify/events.py` | core | 밖으로 보낼 이벤트 고르기와 payload 변환 |
| `src/jarvis/core/notify/dedupe.py` | core | 짧은 시간 안 같은 말 한 번만 |
| `src/jarvis/core/notify/webhook.py` | core | webhook 채널 공통 payload 해석과 POST |
| `src/jarvis/core/notify/slack.py` | core | 슬랙 incoming webhook |
| `src/jarvis/core/notify/discord.py` | core | 디스코드 webhook |
| `src/jarvis/core/notify/discord_voice.py` | core | 디스코드 음성 채널에서 읽기, 없으면 글 |
| `src/jarvis/core/notify/webpush.py` | core | Web Push 구독 저장과 전송 |
| `src/jarvis/ui/web/router/push_router.py` | ui | Web Push REST |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_notify_dedupe.py` |
| 단위 | `tests/unit/test_notify_discord.py` |
| 단위 | `tests/unit/test_notify_discord_voice.py` |
| 단위 | `tests/unit/test_notify_events.py` |
| 단위 | `tests/unit/test_notify_notify.py` |
| 단위 | `tests/unit/test_notify_slack.py` |
| 단위 | `tests/unit/test_notify_webpush.py` |
| 통합 | `tests/integ/test_notify.py` |

**제약과 미구현**: 슬랙, 디스코드 webhook 과 Web Push 에는 중복 제거 키가 없어 재시도하지 않는다. 실패한 알림은 다시 가지 않는다(`# idempotent`).

---

### openloop: 약속 추적(AGENDA)

**설명**: 매 요청 턴에 따로 도는 AGENDA 판단이 새 약속과 끝난 약속을 가려 저장하고, 열린 약속을 사고에 주입하며, Web HUD AGENDA 카드에 스케줄과 함께 보인다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 매 요청 턴 | 새 약속 저장(같은 약속은 병합, 기한 갱신), 끝났거나 취소된 약속 닫기, ws `agenda_changed` |
| `GET /api/agenda` | 스케줄, 열린 약속(20개까지), 최근 닫힌 약속 |
| `POST /api/openloops/{loop_id}` `{status}` | done, dismissed 로 닫기, open 으로 되살리기. 기한이 지난 약속은 되살리지 않음(409) |
| `/openloop`, `/openloop done <id>`, `/openloop dismiss <id>` | 나열, 완료, 무시 |

**처리 흐름**: `AgentSession._spawn_loop_judge` 에서 `judge` 로, `openloop_types` 의 같은 약속 판정과 병합, `openloop_store` (jsonl 또는 Postgres) 저장, 기한 지난 항목 만료, `agenda_router` 조회 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/openloop/judge.py` | agent_layer | AGENDA 판단 LLM 호출 |
| `src/jarvis/agent_layer/openloop/openloop_types.py` | agent_layer | 모델, 기한 해석, 같은 약속 판정, 병합, 만료 규칙 |
| `src/jarvis/agent_layer/openloop/openloop_store.py` | agent_layer | 저장소 기본 클래스와 기한 지난 항목 닫기 |
| `src/jarvis/agent_layer/openloop/jsonl_store.py` | agent_layer | JSONL append 저장소 |
| `src/jarvis/agent_layer/openloop/postgres_store.py` | agent_layer | PostgreSQL 저장소 |
| `src/jarvis/core/slash/openloop_cmd.py` | core | `/openloop` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_openloop_jsonl_store.py` |
| 단위 | `tests/unit/test_openloop_judge.py` |
| 단위 | `tests/unit/test_openloop_openloop_cmd.py` |
| 단위 | `tests/unit/test_openloop_openloop_store.py` |
| 단위 | `tests/unit/test_openloop_openloop_types.py` |
| 단위 | `tests/unit/test_openloop_postgres_store.py` |
| 통합 | `tests/integ/test_openloop.py` |

**제약과 미구현**: 임베딩 벡터는 프로세스 메모리에만 있어 재시작 뒤 첫 판정은 다시 임베딩한다. 조회는 전부 읽어 고른다(모두 `# ponytail`). 뜻이 멀게 바꾼 약속은 따로 쌓이고, 입력과 글자가 거의 겹치지 않는 새 약속은 저장하지 않는다. 약속 수정은 없다(`docs/view_spec.md`).

---

### plugins: 플러그인 훅

**설명**: 디렉터리의 `.py` 파일에서 플러그인 클래스를 찾아 `before_agent_start`, `before_tool_call`, `after_tool_call`, `on_message_end`, `transform_context` 훅을 오류 격리와 체인 적용으로 실행한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `~/.jarvis/plugins/*.py` | 등록된 플러그인 훅이 턴과 도구 호출 앞뒤에서 돈다 |

**처리 흐름**: `plugins_loader` 에서 `PluginRunner` 등록으로, `AgentSession` 이 훅 시점마다 `runner.emit_*` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/plugins/plugins_protocol.py` | core | `JarvisPlugin` 기반 클래스와 `HookResult` |
| `src/jarvis/core/plugins/plugins_loader.py` | core | 디렉터리에서 플러그인 클래스 찾기 |
| `src/jarvis/core/plugins/runner.py` | core | 훅 실행(오류 격리, 체인) |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_plugins_plugins_loader.py` |
| 단위 | `tests/unit/test_plugins_plugins_protocol.py` |
| 단위 | `tests/unit/test_plugins_runner.py` |
| 통합 | 없음. 실제 플러그인 파일을 두고 앱을 띄우는 시나리오가 아직 없다 |

**제약과 미구현**: 없음.

---

### policy: 보안 파이프라인과 접근 키

**설명**: 모든 입력을 검증, 인증, 정책, 샌드박스 4단계로 통과시키고, 사용자별 rate limit 을 건다. Web HUD 는 `JARVIS_SECURITY__API_KEYS` 가 있으면 `/api/*` 와 `/ws` 에 키를 요구한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 사용자 입력 | 길이, 금지 패턴 검증과 정규화, 인증 컨텍스트, 정책 결과, 위험 명령 차단 |
| `/api/*` 요청 | 키가 없거나 틀리면 401 |
| `/ws?token=` | 키가 틀리면 close `4401` |

**처리 흐름**: `AgentSession._prompt` 에서 `SecurityPipeline.run` 으로, `validator`, `authenticator`, `policy`, `sandbox` 순. Web 은 `server` 미들웨어와 `ws_router` 에서 `web_auth` 로 사용자를 찾는다.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/policy/pipeline.py` | core | 4단계 파이프라인 타입, 예외, 단계 기반 클래스 |
| `src/jarvis/core/policy/validator.py` | core | 입력 검증기 |
| `src/jarvis/core/policy/authenticator.py` | core | 익명 통과, API key 인증기 |
| `src/jarvis/core/policy/policy.py` | core | 전부 허용, 역할 기반 정책 엔진 |
| `src/jarvis/core/policy/sandbox.py` | core | 위험 명령 차단과 승인 흐름 |
| `src/jarvis/ui/web/web_auth.py` | ui | Bearer 헤더와 `token` 쿼리로 사용자 찾기 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_policy_app_services.py` |
| 단위 | `tests/unit/test_policy_authenticator.py` |
| 단위 | `tests/unit/test_policy_pipeline.py` |
| 단위 | `tests/unit/test_policy_policy.py` |
| 단위 | `tests/unit/test_policy_sandbox.py` |
| 단위 | `tests/unit/test_policy_validator.py` |
| 단위 | `tests/unit/test_policy_web_auth.py` |
| 통합 | `tests/integ/test_policy.py` |

**제약과 미구현**: 정적 셸(`/`, js, css)은 키 없이 항상 열려 있다(`docs/api_spec.md`).

---

### proactive: 먼저 말 걸기

**설명**: 요청 없이 트리거(주기, 유휴, 외부 이벤트)가 깨울 때 활성 세션을 성찰시켜 말할지 정하고, 오래 걸리는 요청에는 대기 안내(filler)를 먼저 보내고 뒤에서 일한다. 먼저 건넨 말에 대한 사용자의 다음 말을 반응으로 읽어 발화 임계치를 조정한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 트리거 깨움 | ws `proactive_message{kind:"proactive"}`, 세션 기록에 assistant 메시지 |
| 오래 걸리는 요청 | `proactive_message{kind:"filler"}` 뒤 끝나면 `kind:"answer"` |
| 먼저 건넨 말 뒤의 첫 `user_message` | accept, dismiss, 약한 무시로 학습 |
| ws `proactive_feedback{id, accepted}`, TUI `ctrl+y` / `ctrl+g` | 수락, 무시 학습(연결당 같은 `id` 한 번) |

**처리 흐름**: `daemon` 이 `triggers` 를 기다려 `AgentSession.reflect` 로, 성찰 사고, `ProactivityCore` 의 `policy` 게이팅, `_emit_proactive`, `feedback` 학습 순. 요청 시점은 `ProactivityCore.dispatch_request` 가 Dual-Channel 로 filler 와 백그라운드 실행을 가른다.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/proactive/daemon.py` | core | 백그라운드 성찰 루프 |
| `src/jarvis/core/proactive/triggers.py` | core | 주기, 유휴, 외부, 합성 트리거 |
| `src/jarvis/core/proactive/policy.py` | core | Dual-Channel 계획과 자율 발화 게이팅 |
| `src/jarvis/core/proactive/proactive_core.py` | core | 정책, 채널, push 조율 |
| `src/jarvis/core/proactive/proactive_types.py` | core | 발화 메시지, 응답 계획, 게이팅 판정 |
| `src/jarvis/core/proactive/feedback.py` | core | 수락, 무시, 무응답 누적과 임계치 조정 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_proactive_daemon.py` |
| 단위 | `tests/unit/test_proactive_feedback.py` |
| 단위 | `tests/unit/test_proactive_policy.py` |
| 단위 | `tests/unit/test_proactive_proactive_core.py` |
| 단위 | `tests/unit/test_proactive_triggers.py` |
| 통합 | `tests/integ/test_proactive.py` |

**제약과 미구현**: 🔔 가 되풀이인지 볼 때 마지막 답 하나만 본다(`# ponytail`). 성찰에서 🔔 까지 이어지는 시나리오는 e2e 자동화가 없고 수동이다(`TODO.md`).

---

### proactive_eval: proactive 평가

**설명**: "이 상황에서 먼저 말해야 했나"를 jsonl 사례로 적어, 사례마다 새 정책과 고정 시계로 판정하고 지표로 요약한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `uv run python -m jarvis.core.proactive.eval [--suite S] [--engine none\|llm] [--json] [-v]` | 스위트별 판정 지표. `--engine none` 이면 정책만, `llm` 이면 사고 엔진까지 |

**처리 흐름**: `__main__` 에서 `eval_schema` 로 사례 로드, `runner` 가 사례마다 정책을 새로 만들어 판정, 지표 집계 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/proactive/eval/__main__.py` | core | 평가 CLI |
| `src/jarvis/core/proactive/eval/eval_schema.py` | core | 사례 형식 |
| `src/jarvis/core/proactive/eval/runner.py` | core | 판정과 지표 요약 |
| `src/jarvis/core/proactive/eval/datasets/` | core | `policy`, `situation` 사례 jsonl |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_proactive_eval_eval_schema.py` |
| 단위 | `tests/unit/test_proactive_eval_main.py` |
| 단위 | `tests/unit/test_proactive_eval_runner.py` |
| 통합 | 없음. 평가 도구 자체라 CLI 를 끝까지 돌리는 테스트를 두지 않았다 |

**제약과 미구현**: 없음.

---

### procedures: 절차 학습

**설명**: 세션 이력에서 도구를 여러 번 써서 성공한 구간, 또는 같은 작업 종류로 성공한 턴 일화가 쌓인 것을 절차 초안으로 증류하고, 승인된 절차를 LLM 도구와 슬래시 스킬로 노출한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/procedures` | 학습된 절차 목록 |
| `/procedures learn [session_id]` | 세션에서 절차 초안 학습(같은 출처는 한 번만) |
| `/procedures approve <name>`, `reject <name>`, `show <name>` | 승인(도구와 스킬로 등록), 삭제, 본문 보기 |
| 공고화 | 같은 종류 성공 일화가 쌓이면 정제 후보로 증류 |

**처리 흐름**: `detect` 또는 `refine` 에서 `distill` (LLM) 로, `learner` 가 `procedures_store` 에 upsert, 승인 시 `tool` 이 도구와 스킬로 등록, 실행 계획은 `plan` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/procedures/detect.py` | core | 성공한 다단계 작업 구간 찾기 |
| `src/jarvis/core/procedures/distill.py` | core | 구간을 절차 초안으로 증류 |
| `src/jarvis/core/procedures/learner.py` | core | 초안 저장(같은 출처 한 번) |
| `src/jarvis/core/procedures/plan.py` | core | 실행 계획 읽기, 검사, 채우기 |
| `src/jarvis/core/procedures/procedures_store.py` | core | `~/.jarvis/procedures/<name>.md` 저장소 |
| `src/jarvis/core/procedures/tool.py` | core | 승인된 절차를 도구와 스킬로 노출 |
| `src/jarvis/core/slash/procedures_cmd.py` | core | `/procedures` 핸들러 |
| `src/jarvis/memory/long_term/refine.py` | memory | 턴 일화에서 정제 후보 고르기 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_procedures_detect.py` |
| 단위 | `tests/unit/test_procedures_distill.py` |
| 단위 | `tests/unit/test_procedures_learner.py` |
| 단위 | `tests/unit/test_procedures_procedures_cmd.py` |
| 단위 | `tests/unit/test_procedures_procedures_store.py` |
| 단위 | `tests/unit/test_procedures_refine.py` |
| 단위 | `tests/unit/test_procedures_tool.py` |
| 통합 | 없음. 절차 학습은 `scripts/e2e/hud_flow.py` 의 e2e 시나리오로만 돈다 |

**제약과 미구현**: 승인된 절차는 모든 에이전트의 도구가 된다(`# ponytail`).

---

### scheduler: 스케줄러

**설명**: cron 반복 작업과 정한 시각 한 번 실행 작업을 새 세션에서 돌리고 결과를 열린 화면, 대화 세션, 외부 알림 채널로 알린다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/schedule <시각>에 <내용>` | 한 번 실행 작업 등록. LLM 이 알림(reminder)과 작업(task)을 가른다 |
| `/schedule YYYY.MM.DD 오전/오후 N시까지 <프롬프트>` | 반복 작업 등록 |
| `schedule` 도구 | 대화 중 "1분 뒤에 알려줘" 를 같은 규칙으로 등록 |
| `~/.jarvis/schedules/*.yaml` | cron 작업 정의. `kind` 는 `reminder`(문구 그대로), `task`(에이전트 실행), `tool`(도구를 `args` 로 바로 부르기), `goal`(목표 한 차례) 중 하나이고, `agent` 가 작업을 돌릴 최상위 에이전트다 |
| `POST /api/schedules/{name}` `{enabled}` | 켜기, 끄기 |
| 실행 시각 | ws `reminder`, 열린 화면이 없으면 최근 20건을 다음 접속 때 `missed:true` 로. `deliver: conversation` 이면 최근 대화 세션에 `proactive_message` |

**처리 흐름**: `schedule_cmd` 또는 `tool` 에서 `classify` 로, `scheduler_loader` 저장, `SchedulerService` 루프가 때가 된 `ScheduledTask` 를 새 세션에서 실행, 알림 순. `run_until` 이 지난 작업은 `set_enabled` 로 꺼서 저장 파일에도 남기므로 재시작해도 다시 켜지지 않는다.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/scheduler/scheduler_service.py` | core | 스케줄 루프와 실행, 알림 |
| `src/jarvis/core/scheduler/scheduler_loader.py` | core | YAML 읽기, 저장, enabled 토글, 끝난 작업 정리 |
| `src/jarvis/core/scheduler/task.py` | core | 작업 정의 |
| `src/jarvis/core/scheduler/classify.py` | core | reminder, task 분류 |
| `src/jarvis/core/scheduler/tool.py` | core | `schedule` 도구 |
| `src/jarvis/core/slash/schedule_cmd.py` | core | `/schedule` 핸들러와 한국어 시각 해석 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_scheduler_classify.py` |
| 단위 | `tests/unit/test_scheduler_dispatcher.py` |
| 단위 | `tests/unit/test_scheduler_schedule_cmd.py` |
| 단위 | `tests/unit/test_scheduler_scheduler_loader.py` |
| 단위 | `tests/unit/test_scheduler_scheduler_service.py` |
| 단위 | `tests/unit/test_scheduler_task.py` |
| 단위 | `tests/unit/test_scheduler_tool.py` |
| 통합 | `tests/integ/test_scheduler.py` |

**제약과 미구현**: `schedule` 도구를 같은 요청으로 두 번 부르면 알림도 두 개다(`# idempotent`). `reminder` 보류 큐는 메모리에만 있어 재시작하면 사라진다. 화면에서는 켜고 끄기만 되고 만들기와 지우기는 `/schedule` 로 한다(`docs/api_spec.md`, `docs/view_spec.md`).

---

### session: 세션 관리

**설명**: 세션 메타와 메시지를 jsonl 또는 PostgreSQL 에 영속하고, 목록, 새로 만들기, 분기, 삭제, 이력 조회, 대화 내보내기, 토큰 비용 보고, 옛 데이터 정리를 제공한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `GET /api/sessions`, `/sessions` | 세션 목록 |
| `POST /api/sessions {agent}`, TUI `ctrl+n` | 새 세션 |
| `POST /api/sessions/{session_id}/branch`, `/branch [session_id]`, TUI `ctrl+f` | 분기 세션(에이전트 유지) |
| `DELETE /api/sessions/{session_id}` | 삭제(그 세션의 장기 기억과 작업 기억도). 연결이 붙은 세션은 거절 |
| `GET /api/sessions/{session_id}/messages` | 텍스트 이력 |
| `/export md\|json` | 대화 파일 내보내기 |
| `/cost` | 모델별 토큰 사용량과 추정 비용 |
| `/cleanup agents\|stm\|tests [confirm]` | 옛 데이터 현황, `confirm` 이 있을 때만 삭제(per_agent 세션은 보존) |

**처리 흐름**: `session_router` 또는 슬래시 핸들러에서 `SessionRegistry` 와 세션 저장소(`JsonlSessionRepo`, `PostgresSessionRepo`)로, 메타와 메시지 append 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/session/session_protocol.py` | agent_layer | 저장소 기본 클래스, 세션 엔트리, 메타 모델 |
| `src/jarvis/agent_layer/session/jsonl.py` | agent_layer | 세션별 JSONL 저장소 |
| `src/jarvis/agent_layer/session/postgres.py` | agent_layer | PostgreSQL 세션 저장소 |
| `src/jarvis/ui/web/router/session_router.py` | ui | 세션 REST |
| `src/jarvis/core/slash/export_cmd.py` | core | `/export` 핸들러 |
| `src/jarvis/core/slash/cost_cmd.py` | core | `/cost` 핸들러 |
| `src/jarvis/core/slash/cleanup_cmd.py` | core | `/cleanup` 핸들러 |
| `src/jarvis/ui/web/static/app/session.js` | ui | 세션 목록, 전환, 분기, 생성, 재연결 |
| `src/jarvis/ui/web/static/app/usage.js` | ui | SYSTEM 카드 토큰, 비용 집계 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_session_cleanup_cmd.py` |
| 단위 | `tests/unit/test_session_cost_cmd.py` |
| 단위 | `tests/unit/test_session_export_cmd.py` |
| 단위 | `tests/unit/test_session_jarvis_config.py` |
| 단위 | `tests/unit/test_session_jsonl.py` |
| 단위 | `tests/unit/test_session_session_protocol.py` |
| 단위 | `tests/unit/test_session_session_registry.py` |
| 통합 | `tests/integ/test_session.py` |

**제약과 미구현**: Web HUD 세션 목록은 프로세스가 띄운 것만 보인다. Postgres 저장소에서 분기는 히스토리가 복사되지 않은 빈 새 세션이다(`docs/view_spec.md`).

---

### skills: 스킬(명령 매크로)

**설명**: Markdown/YAML 스킬 파일을 읽어 이름과 별칭으로 찾고, `/스킬 인자` 입력을 프롬프트로 펼친다. 승인된 절차도 스킬로 등록된다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `~/.jarvis/skills/*.md`, `*.yaml` | 스킬 등록 |
| `/<스킬 이름> <인자>` | 스킬 본문으로 펼친 프롬프트가 에이전트에 들어간다 |

**처리 흐름**: `AgentSession._prompt` 에서 `SkillRegistry.expand` 로, 이름과 별칭 조회, 인자 치환 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/skills/skills_registry.py` | core | 스킬 로드, 조회, 입력 확장 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_skills_skills_registry.py` |
| 통합 | `tests/integ/test_skills.py` |

**제약과 미구현**: 없음.

---

### task_pattern: 작업 패턴 기억

**설명**: 사용자가 알려 준 일하는 방식(언제, 어떻게)을 부른 에이전트 전용 절차 기억으로 저장하고, 같은 종류 요청에서 그 에이전트에게만 떠올려 되묻지 않게 한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `remember_task_pattern` 도구 | 부른 에이전트 범위로 패턴 저장 |
| `/patterns` | 지금 에이전트의 작업 패턴 목록 |
| `/patterns forget <이름>` | 삭제 |

**처리 흐름**: `task_pattern` 도구에서 `memory.long_term.task_pattern` 변환으로, `MemoryService.remember` 저장, 회상 때 질의 맞추기 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/memory/long_term/task_pattern.py` | memory | 작업 방식을 절차 기억으로 바꾸고 질의에 맞추기 |
| `src/jarvis/core/tools/task_pattern.py` | core | `remember_task_pattern` 도구 |
| `src/jarvis/core/slash/patterns_cmd.py` | core | `/patterns` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_task_pattern_patterns_cmd.py` |
| 단위 | `tests/unit/test_task_pattern_task_pattern.py` |
| 통합 | `tests/integ/test_task_pattern.py` |

**제약과 미구현**: 없음.

---

### thought: inner thought

**설명**: 요청 시점과 성찰 시점에 별도 LLM 호출로 해석, 결정, 확신도를 담은 `ThoughtFrame` 을 만들어 메인 턴 프롬프트에 끼우고 로그로 남긴다. router decision model 이 켜져 있으면 요청마다 사고를 돌릴지 정한다. 키워드로 판정이 안 되는 짧은 답(🔔 피드백, 음성 승인)을 분류한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 요청 턴 | ws `thought_route{think, p_think}`(router 가 켜졌을 때), `inner_thought`, `thought_end`. think 면 사고 결과가 다음 턴 시스템 프롬프트에 한 번 들어간다 |
| 성찰 | `DecisionGatedEngine` 이 "먼저 말할까" 를 decision model 확률로 정한다 |
| ws `reply_classify{kind, id, text, context, has_always}` | `reply_classified{verdict}`. 모델이 없거나 6초 안에 답하지 못하면 `other`, `unclear` |

**처리 흐름**: `AgentSession._route` 에서 `router` (`model_layer.decision`) 로, `engine` 이 `prompt` 템플릿과 회상 콜백으로 `ThoughtFrame` 생성, `composer` 조립, `log` 싱크 저장 순. 분류는 `ws_tasks` 에서 `reply.ReplyClassifier` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/thought/engine.py` | agent_layer | 기본 inner thought 엔진 |
| `src/jarvis/agent_layer/thought/thought_protocol.py` | agent_layer | 엔진 기본 클래스와 회상 콜백 타입 |
| `src/jarvis/agent_layer/thought/thought_types.py` | agent_layer | `ThoughtRequest`, `ThoughtFrame`, 행동 후보 |
| `src/jarvis/agent_layer/thought/prompt.py` | agent_layer | 프롬프트 템플릿 로드와 채우기 |
| `src/jarvis/agent_layer/thought/composer.py` | agent_layer | 프레임을 메인 프롬프트 텍스트로 |
| `src/jarvis/agent_layer/thought/log.py` | agent_layer | 프레임을 LTM, 작업 기억 메모 싱크로 |
| `src/jarvis/agent_layer/thought/router.py` | agent_layer | think, direct 판정 |
| `src/jarvis/agent_layer/thought/decision_gate.py` | agent_layer | 성찰 결정을 decision model 확률로 |
| `src/jarvis/agent_layer/thought/reply.py` | agent_layer | 짧은 답 분류기 |
| `src/jarvis/model_layer/decision.py` | model_layer | decision model(System One API) 클라이언트 |
| `src/jarvis/ui/web/static/app/reply.js` | ui | 화면에서 `reply_classify` 요청 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_thought_composer.py` |
| 단위 | `tests/unit/test_thought_decision.py` |
| 단위 | `tests/unit/test_thought_decision_gate.py` |
| 단위 | `tests/unit/test_thought_engine.py` |
| 단위 | `tests/unit/test_thought_log.py` |
| 단위 | `tests/unit/test_thought_prompt.py` |
| 단위 | `tests/unit/test_thought_reply.py` |
| 단위 | `tests/unit/test_thought_router.py` |
| 단위 | `tests/unit/test_thought_session_builder.py` |
| 단위 | `tests/unit/test_thought_thought_protocol.py` |
| 단위 | `tests/unit/test_thought_thought_types.py` |
| 통합 | `tests/integ/test_thought.py` |

**제약과 미구현**: 클라우드 provider 에서 race(병렬) 타이밍이 맞는지 미측정이다(`TODO.md`). router 가 direct 로 판정한 턴에는 사고와 💬 filler 가 없다(`docs/view_spec.md`).

---

### tools: 내장 도구와 사용자 도구

**설명**: 파일 읽기, 쓰기, 고치기, 목록, glob, grep, 셸, 웹 가져오기, 웹 검색 내장 도구와, 디렉터리의 `.py` / `.yaml` 사용자 도구를 레지스트리에 등록한다. 화면은 세션 에이전트의 도구와 승인 필요 여부를 보인다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| 에이전트의 tool_call | `bash`, `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `web_fetch`, `web_search` 실행 결과 |
| `~/.jarvis/tools/*.py`, `*.yaml` | 기동 때 사용자 도구 등록. 같은 이름의 내장 도구를 덮어쓴다 |
| `GET /api/tools?session_id=`, `/tools` | 도구 목록(`approval` 표시) |

**처리 흐름**: `InfraBuilder` 에서 내장 도구와 `tools_loader` 로 `ToolRegistry` 등록, 세션 에이전트 경계로 거르기, 도구 실행기 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/core/tools/builtin/bash.py` | core | `bash` |
| `src/jarvis/core/tools/builtin/read_file.py` | core | `read_file` |
| `src/jarvis/core/tools/builtin/write_file.py` | core | `write_file` |
| `src/jarvis/core/tools/builtin/edit_file.py` | core | `edit_file` |
| `src/jarvis/core/tools/builtin/list_dir.py` | core | `list_dir` |
| `src/jarvis/core/tools/builtin/glob.py` | core | `glob` |
| `src/jarvis/core/tools/builtin/grep.py` | core | `grep` |
| `src/jarvis/core/tools/builtin/web_fetch.py` | core | `web_fetch` |
| `src/jarvis/core/tools/builtin/web_search.py` | core | `web_search`(Brave, 키 없으면 DuckDuckGo) |
| `src/jarvis/core/tools/tools_loader.py` | core | 파일 기반 도구 로딩 |
| `src/jarvis/ui/web/static/app/tools.js` | ui | SYSTEM 카드 도구 목록 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_tools_bash.py` |
| 단위 | `tests/unit/test_tools_edit_file.py` |
| 단위 | `tests/unit/test_tools_glob.py` |
| 단위 | `tests/unit/test_tools_grep.py` |
| 단위 | `tests/unit/test_tools_list_dir.py` |
| 단위 | `tests/unit/test_tools_read_file.py` |
| 단위 | `tests/unit/test_tools_tools_loader.py` |
| 단위 | `tests/unit/test_tools_tools_registry.py` |
| 단위 | `tests/unit/test_tools_web_fetch.py` |
| 단위 | `tests/unit/test_tools_web_search.py` |
| 단위 | `tests/unit/test_tools_write_file.py` |
| 통합 | `tests/integ/test_tools.py` |

**제약과 미구현**: `ToolLoader.watch`(파일이 바뀌면 다시 읽기)는 있지만 기동 경로에서 부르지 않아, 사용자 도구를 고치면 서버를 다시 띄워야 한다.

---

### tui: 터미널 화면

**설명**: Textual 기반 터미널 화면에서 채팅, 사이드바(세션과 도구), 상태 줄, 슬래시 명령 자동완성, 승인 모달, 음성 입출력을 제공한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `jarvis`, `jarvis --session <id>`, `jarvis --agent <id>` | TUI 기동 |
| `jarvis --list-sessions` | 세션 목록 출력 |
| `/exit`, `ctrl+c` | 종료 |
| `ctrl+b` | 사이드바 토글 |
| `/` 입력 | 슬래시 명령 팝업 |

**처리 흐름**: `startup.parse_startup_plan` 에서 `build_app` 으로, `JarvisTUI` 가 `AgentSession` 이벤트를 `EventBridge` 로 `UIAction` 으로 바꿔 `components` 에 그리는 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/ui/tui/app.py` | ui | Textual 앱과 키 바인딩 |
| `src/jarvis/ui/tui/bridge.py` | ui | 에이전트 이벤트를 `UIAction` 으로 |
| `src/jarvis/ui/tui/state.py` | ui | 렌더링 불변 상태 |
| `src/jarvis/ui/tui/components/chat_history.py` | ui | 채팅 영역 |
| `src/jarvis/ui/tui/components/sidebar.py` | ui | 세션, 도구 사이드바 |
| `src/jarvis/ui/tui/components/slash_picker.py` | ui | 슬래시 명령 자동완성 팝업 |
| `src/jarvis/ui/tui/components/status_bar.py` | ui | 하단 상태 줄 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_tui_bridge.py` |
| 단위 | `tests/unit/test_tui_sidebar.py` |
| 단위 | `tests/unit/test_tui_startup.py` |
| 단위 | `tests/unit/test_tui_ui_protocol.py` |
| 통합 | 없음. 터미널 화면을 띄워 입력을 흘리는 시나리오가 아직 없다 |

**제약과 미구현**: `/focus` 를 쓸 수 없다. TUI 화면 명세가 `docs/view_spec.md` 에 없다(`TODO.md`).

---

### usermodel: 사용자 모델

**설명**: 누적 기억을 LLM 으로 증류해 안정적인 사용자 모델을 만들고, 사고 프롬프트에 블록으로 싣는다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `/usermodel` | 지금 사용자 모델 |
| `/usermodel build` | 최근 기억으로 갱신(실패하면 이전 모델 유지), `~/.jarvis/user_model.json` 스냅샷 |

**처리 흐름**: `usermodel_cmd` 에서 `UserModelBuilder` 로, `MemoryService` 최근 기억 조회, LLM 증류, `usermodel_store` 저장 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/agent_layer/usermodel/builder.py` | agent_layer | 기억을 사용자 모델로 증류 |
| `src/jarvis/agent_layer/usermodel/usermodel_store.py` | agent_layer | 메모리, JSON 파일 저장소 |
| `src/jarvis/agent_layer/usermodel/usermodel_types.py` | agent_layer | 사용자 모델과 프롬프트 블록 변환 |
| `src/jarvis/core/slash/usermodel_cmd.py` | core | `/usermodel` 핸들러 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_usermodel_builder.py` |
| 단위 | `tests/unit/test_usermodel_usermodel_cmd.py` |
| 단위 | `tests/unit/test_usermodel_usermodel_store.py` |
| 단위 | `tests/unit/test_usermodel_usermodel_types.py` |
| 통합 | `tests/integ/test_usermodel.py` |

**제약과 미구현**: 없음.

---

### voice: 음성

**설명**: 서버 STT(faster-whisper)와 TTS(Piper, Supertonic, Qwen3-TTS), 브라우저 Web Speech 위임, 마크다운을 읽을 문장으로 바꾸기, JARVIS 목소리용 영어 번역, 미리 녹음한 읽기 문구, "Jarvis" 웨이크워드 감지를 제공한다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| ws `voice_tts_request{text, id, source, part, full_text, stream}` | `voice_tts_audio`(조각 스트림 가능). 서버 TTS 가 없으면 빈 `data` 로 브라우저가 읽는다 |
| ws `voice_stt_submit{data, mime, sample_rate}` | `voice_stt_result`. 확신도가 낮으면 `unclear` 와 되묻는 말 |
| ws 바이너리 프레임(16kHz PCM) | 점수가 임계치 이상이면 `voice_wake{score}` |
| `GET /api/voice/phrases/{name}` | 녹음 문구 wav |
| Web HUD 구체 클릭, DEFAULT / FULL-VOICE, TUI `ctrl+t` / `ctrl+r` | 읽기 토글, 모드 전환, 음성 입력 |

**처리 흐름**: `ws_tasks` 에서 `speech_text` 로 기호 제거와 금액 한글화, 필요하면 `english` 번역, `VoiceService` 가 `voice_registry` 로 고른 프로바이더 합성 또는 전사 순. 웨이크워드는 `ws_router` 에서 `WakeDetector` 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/voice/voice_service.py` | voice | STT, TTS 파이프라인 |
| `src/jarvis/voice/voice_registry.py` | voice | 이름으로 프로바이더 지연 생성 |
| `src/jarvis/voice/voice_protocol.py` | voice | 프로바이더 기본 클래스(브라우저 위임) |
| `src/jarvis/voice/speech_text.py` | voice | 마크다운을 읽을 문장으로 |
| `src/jarvis/voice/english.py` | voice | 한국어 글을 짧은 영어 구어체로 |
| `src/jarvis/voice/phrases.py` | voice | 읽기 문구 폴더 로드 |
| `src/jarvis/voice/wake.py` | voice | 웨이크워드 감지기 |
| `src/jarvis/voice/providers/browser.py` | voice | 브라우저 위임 프로바이더 |
| `src/jarvis/voice/providers/whisper.py` | voice | faster-whisper STT |
| `src/jarvis/voice/providers/piper.py` | voice | Piper TTS |
| `src/jarvis/voice/providers/supertonic.py` | voice | Supertonic-3 TTS |
| `src/jarvis/voice/providers/qwen.py` | voice | Qwen3-TTS, 실패하면 Piper |
| `src/jarvis/ui/web/router/voice_router.py` | ui | 읽기 문구 wav REST |
| `src/jarvis/ui/tui/voice.py` | ui | TUI 음성 컨트롤러 |
| `src/jarvis/ui/web/static/voice.js` | ui | `VoiceManager` |
| `src/jarvis/ui/web/static/app/voice-ui.js` | ui | 음성 입출력 배선과 Full-voice 흐름 |
| `src/jarvis/ui/web/static/app/phrases.js` | ui | 읽기 문구 재생 |
| `src/jarvis/ui/web/static/app/wake.js` | ui | 웨이크워드 오디오 송신 |
| `src/jarvis/ui/web/static/wake-worklet.js` | ui | 80ms PCM 캡처 AudioWorklet |
| `src/jarvis/ui/web/static/app/mode.js` | ui | DEFAULT, FULL-VOICE 모드 세그먼트 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_voice_english.py` |
| 단위 | `tests/unit/test_voice_phrases.py` |
| 단위 | `tests/unit/test_voice_piper.py` |
| 단위 | `tests/unit/test_voice_qwen.py` |
| 단위 | `tests/unit/test_voice_speech_text.py` |
| 단위 | `tests/unit/test_voice_supertonic.py` |
| 단위 | `tests/unit/test_voice_voice.py` |
| 단위 | `tests/unit/test_voice_voice_protocol.py` |
| 단위 | `tests/unit/test_voice_voice_registry.py` |
| 단위 | `tests/unit/test_voice_voice_service.py` |
| 단위 | `tests/unit/test_voice_wake.py` |
| 단위 | `tests/unit/test_voice_whisper.py` |
| 통합 | `tests/integ/test_voice.py` |

**제약과 미구현**: 영어 문장 나누기가 약어 마침표에서도 나뉜다(`# ponytail`). 웨이크워드는 영어 발음 "Jarvis" 만 알아듣고 16kHz AudioContext 를 쓸 수 있는 브라우저에서만 돈다. 읽기가 겹치면 소리가 겹친다(`docs/view_spec.md`). 에어팟에서 승인 되읽기 확인이 남아 있다(`TODO.md`).

---

### web_hud: Web HUD

**설명**: FastAPI 앱이 정적 HUD 셸(리액터 캔버스, 입자 구, 카드, 입력 독)과 REST, WebSocket 라우터를 묶어 띄우고, 기동 때 첫 세션, 스케줄러, 성찰 daemon, 외부 폴러를 켠다.

**입력과 결과**

| 입력 | 결과 |
|---|---|
| `jarvis --web [--host] [--port]` | uvicorn 으로 Web HUD 기동(기본 `127.0.0.1:7777`) |
| `/` 화면 | HUD 셸, 접속하면 `default` 세션(JARVIS) |
| 종료 | 세션마다 공고화와 저장 |

**처리 흐름**: `startup` 에서 `build_app` 과 `server.create_app` 으로, `web_lifecycle` 기동, 라우터 등록, `StaticFiles` 셸 서빙 순.

**구현 파일**

| 파일 | 층 | 역할 |
|---|---|---|
| `src/jarvis/ui/web/server.py` | ui | FastAPI 앱 조립과 인증 미들웨어 |
| `src/jarvis/ui/web/startup.py` | ui | uvicorn 실행 |
| `src/jarvis/ui/web/web_lifecycle.py` | ui | 기동과 종료 |
| `src/jarvis/ui/web/static/index.html` | ui | HUD 셸 |
| `src/jarvis/ui/web/static/styles.css` | ui | 스타일 |
| `src/jarvis/ui/web/static/hud.js` | ui | 리액터 캔버스(링, 눈금, 별) |
| `src/jarvis/ui/web/static/sphere.js` | ui | three.js 입자 구 |
| `src/jarvis/ui/web/static/sw.js` | ui | 셸 프리캐시와 오프라인 폴백 |
| `src/jarvis/ui/web/static/manifest.json` | ui | PWA manifest 원본 |
| `src/jarvis/ui/web/static/icons/` | ui | 앱 아이콘 |
| `src/jarvis/ui/web/static/vendor/three/` | ui | three.js 벤더 파일 |
| `src/jarvis/ui/web/static/app/main.js` | ui | HUD 진입점 |
| `src/jarvis/ui/web/static/app/shell.js` | ui | 헤더, 캡션, ACTIVITY, 카드 접기, 드로어 |
| `src/jarvis/ui/web/static/app/artifact.js` | ui | 큰 코드블록 아티팩트 패널 |

**테스트**

| 종류 | 파일 |
|---|---|
| 단위 | `tests/unit/test_web_hud_adapter.py` |
| 단위 | `tests/unit/test_web_hud_logger.py` |
| 단위 | `tests/unit/test_web_hud_ws_tasks.py` |
| 통합 | `tests/integ/test_web_hud.py` |

**제약과 미구현**: 오른쪽 여백(헤더와 스테이지가 창보다 좁게 보임) 사용자 보고가 재현되지 않아 열려 있다(`TODO.md`). 입력창은 한 줄이다. 아티팩트 패널은 응답 하나에 코드블록 하나만 보인다(`docs/view_spec.md`).

---

## 공통 모듈

여러 기능이 함께 쓰는 파일.

| 파일 | 역할 | 쓰는 기능 |
|---|---|---|
| `src/jarvis/jarvis_config.py` | env 와 `.env` 에서 읽는 전체 설정 | 전체 |
| `src/jarvis/common/logger.py` | structlog 로거 설정. 출력 형식은 `LOG_FORMAT`(`console` 기본, `json`), 레벨은 `JARVIS_LOG_LEVEL`(기본 `INFO`) | 전체 |
| `src/jarvis/core/session.py` | `AgentSession`: 보안, 플러그인, 스킬, 사고, proactive 를 묶어 한 턴과 성찰 실행 | 전체 |
| `src/jarvis/agent_layer/agent_types.py` | 루프 이벤트, 실행 컨텍스트, 루프 설정 | 전체 |
| `src/jarvis/app/app_assembly.py` | 기동 한 번의 조립 결과 | 전체 |
| `src/jarvis/app/app_context.py` | 화면이 붙잡는 앱 단위 인프라 묶음 | 전체 |
| `src/jarvis/app/app_services.py` | 세션 생성 때 넘기는 앱 단위 서비스 묶음 | 전체 |
| `src/jarvis/app/infra_builder.py` | 도구, 메모리, 저장소, 보안, 스케줄러, proactive, 슬래시 명령 조립 | 전체 |
| `src/jarvis/app/session_builder.py` | `AgentProfile` 과 서비스로 `AgentSession` 조립 | 전체 |
| `src/jarvis/app/agent_profile.py` | 에이전트 한 명분 정체성, 모델, 사고와 proactive 설정 | agent_registry, thought, proactive |
| `src/jarvis/core/tools/tools_registry.py` | `JarvisTool` 기반 클래스와 `ToolRegistry` | tools, mcp, housing, goal, scheduler, memory, task_pattern, multi_agent, agent_conversation, procedures |
| `src/jarvis/core/slash/dispatcher.py` | 텍스트의 `/command` 를 핸들러로 실행하고 `/help` 제공 | 모든 슬래시 명령 기능 |
| `src/jarvis/core/slash/ops_cmd.py` | `/sessions`, `/branch`, `/tools`, `/compact` 핸들러 | session, tools, memory |
| `src/jarvis/model_layer/model_types.py` | 메시지, 콘텐츠 블록, 스트림 이벤트, 모델 설정 타입 | 전체 |
| `src/jarvis/model_layer/model_registry.py` | 이름으로 LLM 프로바이더 등록과 조회 | 전체 |
| `src/jarvis/model_layer/stream.py` | 프로바이더 스트리밍과 메시지 수집 | agent_loop, thought, openloop, journal, usermodel, procedures, memory, focus |
| `src/jarvis/model_layer/providers/provider_base.py` | 프로바이더 기본 클래스 | agent_loop |
| `src/jarvis/model_layer/providers/anthropic.py` | Anthropic 스트리밍(프롬프트 캐싱) | agent_loop |
| `src/jarvis/model_layer/providers/openai.py` | OpenAI 스트리밍 | agent_loop |
| `src/jarvis/model_layer/providers/gemini.py` | Gemini 스트리밍 | agent_loop |
| `src/jarvis/model_layer/providers/ollama.py` | Ollama NDJSON 스트리밍. id 없이 온 도구 호출에는 `{이름}_{순번}` id 를 붙여, 같은 도구를 두 번 불러도 호출이 합쳐지지 않는다 | agent_loop |
| `src/jarvis/model_layer/providers/vllm.py` | vLLM SSE 스트리밍 | agent_loop |
| `src/jarvis/model_layer/embeddings.py` | 임베딩 프로바이더 | memory, openloop |
| `src/jarvis/ui/ui_protocol.py` | 화면이 이벤트, 스트림, 승인, 오류를 받는 기본 어댑터 | tui, web_hud |
| `src/jarvis/ui/tui/startup.py` | `jarvis` 명령 인자를 `StartupPlan` 으로 정규화하고 TUI 나 Web 을 띄운다 | tui, web_hud |
| `src/jarvis/ui/web/web_state.py` | Web 라우터가 같이 보는 실행 상태 | web_hud, focus, voice, notify, agent_conversation, thought |
| `src/jarvis/ui/web/router/ws_router.py` | `/ws` 연결 수명과 메시지 분기 | agent_loop, approval, focus, proactive, thought, voice, notify |
| `src/jarvis/ui/web/ws_tasks.py` | ws 메시지가 띄우는 프롬프트, STT, TTS, 분류 작업 | agent_loop, voice, thought, proactive |
| `src/jarvis/ui/web/adapter.py` | 에이전트 이벤트를 연결 하나로 보내는 어댑터 | web_hud 의 모든 ws 이벤트 |
| `src/jarvis/ui/web/session_registry.py` | Web 세션 생성, 조회, 삭제, 스케줄 결과를 건넬 세션 고르기 | session, scheduler, agent_registry, web_hud |
| `src/jarvis/ui/web/web_schema.py` | REST 요청 본문 모델 | session, openloop, scheduler, notify |
| `src/jarvis/ui/web/router/agenda_router.py` | `GET /api/agenda`, `POST /api/openloops/{loop_id}`, `POST /api/schedules/{name}` | openloop, scheduler, goal |
| `src/jarvis/ui/web/router/tool_router.py` | `GET /api/tools`, `GET /api/slash-commands` | tools, 모든 슬래시 명령 기능 |
| `src/jarvis/ui/web/static/app/api.js` | REST 호출과 접근 키 저장 | web_hud, policy, session, openloop, tools, agent_registry, voice |
| `src/jarvis/ui/web/static/app/ws.js` | WebSocket 전송 | web_hud 전체 |
| `src/jarvis/ui/web/static/app/events.js` | 서버 이벤트를 화면 변화로 | web_hud 전체 |
| `src/jarvis/ui/web/static/app/messages.js` | CONVERSATION 메시지 DOM | agent_loop, thought, proactive, scheduler |
| `src/jarvis/ui/web/static/app/markdown.js` | 의존 없는 마크다운 렌더 | agent_loop, focus, scheduler, proactive |
| `src/jarvis/ui/web/static/app/composer.js` | 입력창, 슬래시 자동완성, Ctrl+K 중단 | agent_loop, 모든 슬래시 명령 기능, voice |
| `src/jarvis/ui/web/static/app/agenda.js` | AGENDA 카드와 스케줄 알림 | openloop, scheduler, goal |
