---
sidebar_position: 1
title: JARVIS 도구
---

# JARVIS 도구

JARVIS 는 정의 파일이 없어서 도구 목록(`tools`)도 비어 있다. 그래서 앱 레지스트리에 등록된 도구 전체를 쓴다. 다른 에이전트는 정의 파일의 `tools` 에 적은 도구만 받으므로, 셸과 파일 쓰기처럼 권한이 큰 도구를 기본으로 가진 에이전트는 JARVIS 하나다.

## 내장 도구

서버가 뜰 때 항상 등록되는 도구다(`app/infra_builder.py` 의 `build_tool_registry`).

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

승인이 필요한 도구에서 **항상 허용** 을 고르면 규칙이 `~/.jarvis/approvals/main.yaml` 에 쌓인다. 대조 방식은 [Tool & Approve System](../../concepts/conversation/tools-and-approval.md#승인-기억)에 있다.

## 설정과 실행 중에 붙는 도구

아래 도구는 설정이 있거나 실행 중에 만들어지면 앱 레지스트리에 들어오고, JARVIS 는 따로 고르지 않아도 받는다.

| 도구 | 언제 붙나 | 자세히 |
|---|---|---|
| `agent_<name>`, `orchestrate` | 서브 에이전트 정의가 있을 때 | [Orchestration Pattern](../../concepts/multi-agent-orchestration/orchestration-pattern.md) |
| `procedure_<name>` | 여러 도구로 성공한 작업을 절차로 승인했을 때 | [Memory Management](../../concepts/memory.md) |
| MCP 서버의 도구 | MCP 서버를 연결했을 때 | [Extension](../../concepts/extension.md#mcp-서버) |
| 사용자 도구 | `~/.jarvis/tools/` 에 도구 파일을 두었을 때 | [Extension](../../concepts/extension.md#도구) |

사용자 도구와 MCP 도구는 같은 이름의 내장 도구를 덮어쓴다.

## 모든 에이전트가 함께 쓰는 도구

| 도구 | 하는 일 |
|---|---|
| `ask_agent` | 다른 최상위 에이전트에게 일을 맡긴다. 에이전트가 둘 이상일 때만 있다([Multi agent Orchestration](../../concepts/multi-agent-orchestration/index.md#에이전트끼리-대화)) |
| `remember_task_pattern` | 사용자가 알려 준 작업 방식을 JARVIS 의 작업 패턴으로 저장한다([Memory Management → 작업 패턴](../../concepts/memory.md#작업-패턴)) |

## 갖지 않는 도구

`lh_notice`, `sh_notice`, `housing_budget`, `housing_loan` 은 에이전트 전용 도구라서 JARVIS 에게 없다. 청약 질문을 받으면 JARVIS 는 `ask_agent` 로 [KAREN](../karen/index.md)에게 맡긴다.
