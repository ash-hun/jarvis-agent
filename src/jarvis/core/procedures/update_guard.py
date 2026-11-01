"""[core] reflector 제안을 모델과 무관한 규칙으로 거르는 순수 함수. 통과하면 None, 막으면 이유 한 줄을 돌려준다."""

import re

from jarvis.core.procedures.reflect import ACTION_NONE, ACTION_PATTERN, SCOPE_ACTIONS, FailureCase, Reflection

MAX_CONTENT_CHARS = 1500
COPY_CHARS = 40  # 실패 입력에서 이만큼 이어진 글을 그대로 옮기면 일반화가 아니라 베끼기다
MIN_REFERENCE_CHARS = 3  # 이보다 짧은 정답(보기 기호, 한 자리 수)은 낱말로 흔해 막지 않는다


def check(proposal: Reflection, case: FailureCase, room: bool) -> str | None:
    """EMMA 의 거름망 순서를 따른다. 범위-행동, 정답과 원문 누출, 크기, 상한.

    room 은 이 제안이 새 항목을 만들 때 에이전트당 상한 안에 자리가 있는지다(기존 항목 개정이면 늘 참).
    """
    expected = SCOPE_ACTIONS[proposal.scope]
    if proposal.action != expected:
        return f"범위 {proposal.scope} 에는 {expected} 만 쓸 수 있다({proposal.action} 은 다른 범위의 행동이다)"
    if proposal.action == ACTION_NONE:
        return None
    if not proposal.content.strip():
        return "content 가 비었다"
    if len(proposal.content) > MAX_CONTENT_CHARS:
        return f"content 가 {MAX_CONTENT_CHARS}자를 넘는다. 가장 작은 수정 하나로 줄인다"
    if proposal.action == ACTION_PATTERN and not (proposal.when.strip() and _keywords(proposal)):
        return "task_pattern 에는 when 과 두 글자 이상 keywords 가 하나 이상 있어야 한다"
    text = " ".join((proposal.name, proposal.when, proposal.content, *proposal.keywords))
    if any(leaks_reference(text, ref) for ref in case.references):
        return "이번 작업의 정답이 들어 있다. 정답이 아니라 방법을 쓴다"
    copied = copied_span(text, [a.request for a in case.attempts])
    if copied:
        return f"실패 입력을 그대로 옮겼다({copied[:COPY_CHARS]}…). 일반화해서 다시 쓴다"
    if not room:
        return "이 에이전트의 절차 수가 상한이다. 있는 절차를 고치는 수정만 받는다"
    return None


def leaks_reference(text: str, reference: str) -> bool:
    ref = _norm(reference)
    if len(ref) < MIN_REFERENCE_CHARS:
        return False
    return re.search(rf"(?<!\w){re.escape(ref)}(?!\w)", _norm(text)) is not None


def copied_span(text: str, sources: list[str], size: int = COPY_CHARS) -> str:
    """text 의 size 자 조각 중 sources 어딘가에 그대로 있는 첫 조각. 없으면 빈 문자열."""
    body = _norm(text)
    haystack = "\n".join(_norm(s) for s in sources)
    for i in range(0, max(len(body) - size + 1, 0)):
        piece = body[i : i + size]
        if piece in haystack:
            return piece
    return ""


def _keywords(proposal: Reflection) -> list[str]:
    return [k for k in proposal.keywords if len(k.strip()) >= 2]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
