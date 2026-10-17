"""[core] Focus sub-agent 넷의 역할 지시문과, 메인 에이전트에 덧붙일 Focus 맥락을 조립한다."""

from typing import Any

from jarvis.core.focus.types import FocusState, progress, render_analysis

REFERENCE_TOOLS = ["web_search", "web_fetch", "glob", "grep", "read_file", "list_dir"]
REFERENCE_PROMPT_MAX = 1500
INSTRUCTION_HISTORY = 6

REFERENCE_SYSTEM = """너는 Focus 모드의 외부 레퍼런스 조사 담당이다.
사용자의 작업과 비슷한 선례를 web_search, web_fetch 로 웹에서, glob, grep, read_file 로 로컬 파일에서 찾는다.
답하기 전에 반드시 web_search 를 한 번 이상 호출한다.
검색어를 바꿔 가며 두세 번 찾고, 쓸 만한 결과는 web_fetch 로 본문을 읽는다.
찾은 선례에서 이번 작업에 쓸 수 있는 특징만 추린다. 도구 결과에 없는 내용, 출처가 없는 내용은 쓰지 않는다.

조사한 내용이 많아도 짧게 정리한다. 화면의 작은 영역에 그대로 보인다.
- 선례는 많아야 3개다
- 선례마다 출처 한 줄과 특징 두 줄 이하다. 특징은 한 줄에 한 가지만, 60자 이내 한 문장이다
- 모두 한국어로 쓴다. 영어 자료도 한국어로 옮겨 요약한다
- 검색 결과의 목록(상위 10개 같은)을 옮겨 적지 않는다. 번호 목록과 하위 목록을 쓰지 않는다

출력 형식:
### <선례 이름>
- 출처: <URL 또는 파일 경로>
- <특징 한 문장>

#### 적용할 점
- <이번 작업에 적용할 점, 3개 이하>

선례를 찾지 못했으면 찾지 못했다고만 쓴다."""

LOG_SYSTEM = """너는 Focus 모드의 서기다. 작업 진행을 기록해, 오랜 시간이 지난 뒤 처음 읽는 사람도 완전히 이해하게 한다.

규칙:
- 3인칭으로 쓴다. 주체를 "사용자", "JARVIS" 처럼 명시한다. "나", "우리", "너" 를 쓰지 않는다.
- 상대적 표현을 쓰지 않는다. "아까", "방금", "어제", "이것", "그거", "위에서", "아래와 같이", "앞의" 대신
  시각과 이름을 쓴다.
- 지칭은 진행 과정에 실제로 등장한 이름(파일명, 도구명, 사람이 붙인 이름)만 쓴다. 새 별칭을 만들지 않는다.
- 무엇을 했고, 왜 했고, 결과가 무엇인지 쓴다. 추측은 "추정" 으로 표시한다.

출력은 기록 한 건이다.
### <시각> <한 줄 제목>
<3~6문장 본문>"""

ANALYSIS_SYSTEM = """너는 Focus 모드의 지시 분석 담당이다. 사용자의 이번 지시를 다섯 항목으로 분석한다.
1. purpose: 이 지시의 근본 목적
2. reuse: 이전 지시들 중 이번 지시에 도움이 되는 것
3. needs: 이 지시를 이루는 데 필요한 것(정보, 도구, 결정)
4. next: 예상되는 다음 사용자 지시
5. prepare: 예상 다음 지시에 대비해 미리 조사하거나 준비할 것
그리고 research: 지금 웹이나 로컬에서 조사하면 도움이 될 검색어
(없으면 빈 목록, 많아야 2개)

JSON 하나만 출력한다. 각 항목은 짧은 문장의 목록이다.
{"purpose": [], "reuse": [], "needs": [], "next": [], "prepare": [], "research": []}"""

PROGRESS_SYSTEM = """너는 Focus 모드의 진행 관리 담당이다.
작업을 완료까지의 단계로 나누고, 대화를 보고 끝난 단계를 표시한다.
단계는 3~8개, 각 단계는 결과물이 분명한 짧은 명사구로 쓴다.
이미 있는 단계의 이름은 바꾸지 않는다. 작업 범위가 넓어졌을 때만 단계를 더한다.
JSON 하나만 출력한다.
{"steps": [{"title": "<단계>", "done": false}]}"""

SYSTEM_PROMPTS = {
    "reference": REFERENCE_SYSTEM,
    "log": LOG_SYSTEM,
    "analysis": ANALYSIS_SYSTEM,
    "progress": PROGRESS_SYSTEM,
}


def reference_request(task: str, query: str) -> str:
    return f"작업: {task}\n조사할 것: {query}"


def log_request(timestamp: str, instruction: str, reply: str) -> str:
    return f"시각: {timestamp}\n사용자 지시: {instruction}\nJARVIS 응답:\n{reply}"


def analysis_request(state: FocusState, instruction: str) -> str:
    earlier = "\n".join(f"- {text}" for text in state.instructions[-INSTRUCTION_HISTORY:]) or "- 없음"
    return f"작업: {state.task}\n이전 지시:\n{earlier}\n이번 지시: {instruction}"


def progress_request(state: FocusState, instruction: str, reply: str) -> str:
    steps = "\n".join(f"- [{'x' if s.done else ' '}] {s.title}" for s in state.steps) or "- 아직 없음"
    return f"작업: {state.task}\n현재 단계:\n{steps}\n이번 지시: {instruction}\nJARVIS 응답:\n{reply}"


def main_addendum(state: FocusState, analysis: dict[str, Any] | None, references: str) -> str:
    """메인 에이전트 시스템 프롬프트에 덧붙일 Focus 맥락. 분석이 이번 응답의 방향을 잡는다."""
    steps = "\n".join(f"- [{'x' if s.done else ' '}] {s.title}" for s in state.steps) or "- 아직 없음"
    parts = [
        "[Focus 모드] 사용자는 아래 작업 하나에 집중하고 있다. 모든 응답을 이 작업의 완성도를 높이는 쪽으로 한다.",
        f"작업: {state.task}",
        f"진행 단계 ({round(progress(state.steps) * 100)}%):\n{steps}",
    ]
    if analysis:
        parts.append("직전 지시 분석:\n" + render_analysis(analysis))
    if references.strip():
        parts.append("참고 레퍼런스(요약):\n" + references.strip()[-REFERENCE_PROMPT_MAX:])
    return "\n\n".join(parts)
