---
sidebar_position: 5
title: 도구와 승인
---

# 도구와 승인

에이전트가 세상에 손을 대는 길은 도구뿐이다. 도구는 `core/tools/` 의 레지스트리에 모이고, 위험한 도구는 `core/policy/sandbox.py` 가 실행 전에 사람에게 묻는다.

## 내장 도구

| 도구 | 하는 일 | 승인 |
|---|---|---|
| `bash` | 셸 명령. 기본 타임아웃 30초 | 필요 |
| `write_file` | 파일 쓰기. 부모 디렉토리 생성, 덮어쓰기 | 필요 |
| `edit_file` | 문자열 정밀 교체 | 필요 |
| `read_file` | 라인 범위 읽기 | |
| `glob` | 패턴으로 파일 찾기, 최근 수정순 | |
| `grep` | 정규식 검색, 바이너리 건너뜀 | |
| `list_dir` | 디렉토리 나열 | |
| `web_search` | Brave(키 있으면) 또는 DuckDuckGo | |
| `web_fetch` | URL 본문을 텍스트로 | |

에이전트만 쓰는 도구: `lh_notice`, `sh_notice`, `housing_loan`. 앱 레지스트리에 넣지 않고 에이전트 정의의 `tools` 에 이름을 적은 에이전트만 받는다([청약 공고와 대출 계산](./housing.md)).

동적으로 더해지는 도구: `orchestrate` 와 `agent_<name>`(에이전트 정의가 있을 때), `procedure_<name>`(승인된 절차), MCP 서버의 도구, `~/.jarvis/tools/` 의 사용자 도구. 사용자 도구와 MCP 도구는 같은 이름의 내장 도구를 덮어쓴다. 도구 목록은 턴마다 다시 읽으므로 새로 등록된 도구가 재시작 없이 보인다.

## 도구 호출 한 번

```mermaid
flowchart TD
  L[LLM 이 도구 호출] --> A{정책 허용 목록}
  A -- 없음 --> E1[is_error 결과: not permitted]
  A --> B{플러그인 before_tool_call}
  B -- block --> E2[is_error 결과: reason]
  B --> C{승인 필요 도구?}
  C -- 아니오 --> X[실행]
  C -- 예 --> D{공용 또는 에이전트 규칙에 맞나?}
  D -- 예 --> X
  D -- 아니오 --> U[사용자에게 묻기<br/>ALLOW / ALWAYS / DENY, 120초]
  U -- ALLOW --> X
  U -- ALWAYS --> W[규칙 저장] --> X
  U -- DENY 또는 시간 초과 --> E3[is_error 결과: denied]
  X --> P[플러그인 after_tool_call]
  P --> R[결과를 LLM 에]
```

거부는 예외가 아니다. LLM 은 "denied" 결과를 보고 다른 길을 찾거나 사용자에게 말한다. 루프는 최대 20턴.

## 승인 기억

규칙 파일은 두 겹이다. 둘 중 하나라도 맞으면 묻지 않는다.

| 파일 | 누가 쓰나 | 누구에게 적용 |
|---|---|---|
| `~/.jarvis/approvals.yaml` (공용) | 사람이 직접 고친다 | 모든 에이전트 |
| `~/.jarvis/approvals/<agent_id>.yaml` | 승인 화면의 **항상 허용** | 그 에이전트만 |

승인 화면에서 **항상 허용**(TUI `a`, Web `ALWAYS`)을 고르면 서버가 제안한 패턴이 지금 세션의 에이전트 파일에 남는다. KAREN 에서 허용한 명령이 JARVIS 로 번지지 않는다. 공용 파일에 이미 있는 규칙이면 아무 파일도 건드리지 않는다. 규칙은 사용자가 그 버튼을 눌렀을 때만 생긴다.

| 도구 | 제안 패턴 | 대조 |
|---|---|---|
| `bash` | 명령의 앞 두 단어 (`git status`) | 토큰 접두. `git status --short` 는 통과, `git stash` 는 다시 묻는다 |
| `write_file`, `edit_file` | 경로의 디렉토리 (`src/app/*`) | glob |
| 그 외 | `*` | 도구 전체 |

```yaml
# ~/.jarvis/approvals/main.yaml  손으로 고쳐도 된다. 쓰기는 임시 파일 뒤 교체라 중간에 죽어도 깨지지 않는다
rules:
  - {tool: bash, pattern: uv run}
  - {tool: write_file, pattern: "docs/*"}
```

승인이 필요한 도구 목록은 `JARVIS_SECURITY__REQUIRE_APPROVAL_FOR`(기본 `bash`, `write_file`, `edit_file`). 규칙 파일 하나를 앱 전체가 공유한다.

## Web 에서의 승인

세션마다 승인 브로커(`ui/web/approvals.py`)가 하나 있다. 요청은 그 세션에 붙은 모든 연결에 가고, 먼저 온 답을 쓴다. 기다리는 중에 새로 붙은 탭에도 보여주고, 끝나면 `approval_resolved` 로 나머지 모달을 닫는다. 연결이 하나도 없으면 바로 거부. TUI 는 다이얼로그에서 `y`, `a`, `n`.

## 절차 학습

여러 도구를 써서 성공으로 끝난 작업을 재사용 가능한 절차로 증류한다. 구현은 `core/procedures/`.

```mermaid
flowchart TD
  S[세션 종료 또는 procedures learn] --> F[구간 찾기: 사용자 메시지 사이, 도구 3회 이상, 오류 0]
  F --> K{이미 배운 구간인가}
  K -- 예 --> N[건너뜀]
  K -- 아니오 --> D[LLM 증류: name, description, parameters, steps]
  D --> W[procedures 폴더에 draft 로 저장]
  W --> A[procedures approve]
  A --> T[도구 procedure_name 과 스킬 등록]
```

- 구간에 도구 오류가 하나라도 있으면 배우지 않는다. 실패했다가 회복한 것도 제외
- 같은 구간은 두 번 배우지 않는다. 세션 종료 훅을 다시 돌려도 파일이 늘지 않는다
- 이름이 겹치면 해시 접미사가 붙는다
- 절차 도구는 레시피를 돌려주고 에이전트가 따른다. 직접 실행하지 않는다. 지시문에 "단계를 건너뛰지 말고 각 도구 호출을 실제로 실행하라" 가 들어 있다

```markdown
---
name: list-md-files-and-read-readme-summary
description: 마크다운 파일 목록을 보고 README 앞부분을 요약하는 절차
status: approved
source: default#32
tools: [glob, read_file, bash]
parameters: '1. 파일 검색 패턴, 2. 주요 파일 경로, 3. 읽을 최대 줄 수'
---
요청 예: 현재 디렉토리의 md 파일 목록을 보고 README.md 앞 20줄을 읽고 echo done 을 실행해서 요약해줘
이번 입력: {{args}}

절차:
1. glob 으로 파일 목록 검색
2. read_file 로 README.md 20줄
3. bash echo done
```

## 스킬, 플러그인, MCP

- **스킬**: `~/.jarvis/skills/*.md`. `/name args` 가 본문으로 펼쳐져 LLM 프롬프트가 된다. 기동 때 한 번 읽는다
- **플러그인**: `~/.jarvis/plugins/*.py`. 실제로 불리는 훅은 `before_agent_start`, `before_tool_call`(block 가능), `after_tool_call`(관찰만, 반환값은 무시), `on_message_end`(응답 교체 가능). `transform_context` 는 선언만 되어 있고 호출되지 않는다. 플러그인 하나의 오류는 격리된다
- **MCP**: `mcp_servers` 설정의 서버에서 도구를 발견해 등록한다. `stdio` 와 SSE. 호출마다 새 연결을 연다. 서버 하나의 실패가 다른 서버를 막지 않는다. `uv sync --extra mcp`

파일 감시(`JARVIS_PLUGIN__WATCH_FILES`)는 설정에 있지만 현재 아무것도 감시하지 않는다. 도구, 스킬, 플러그인을 더했으면 재시작한다.

## 보안 파이프라인

모든 입력은 검증, 인증, 정책 순으로 지난다.

- **검증**: 빈 입력, `JARVIS_SECURITY__INPUT_MAX_LENGTH`(10,000자) 초과, `<script>`, `javascript:`, `on*=` 패턴을 막는다. NFC 정규화와 HTML 이스케이프
- **인증**: TUI 는 로컬 사용자. Web 은 `JARVIS_SECURITY__API_KEYS` 가 있을 때만 키를 요구한다. 키의 `name` 이 메모리 범위와 요청 제한의 사용자 id 가 된다
- **정책**: 현재는 모든 도구 허용 정책이 배선되어 있다. 역할 기반 정책 클래스는 있지만 쓰이지 않는다

위험 명령 정규식(`JARVIS_SECURITY__DANGEROUS_COMMANDS`)은 설정에 있지만 도구 호출 경로에서는 검사되지 않는다. 지금의 안전장치는 승인 모달과 승인 규칙이다.
