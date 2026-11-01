"""procedures 기능의 거름망: 범위-행동 일치, 정답과 원문 누출, 크기, 에이전트당 상한."""

import pytest

from jarvis.core.procedures.update_guard import COPY_CHARS, check, copied_span, leaks_reference
from tests.fixtures.procedures_helpers import PATTERN_FIX, PROCEDURE_FIX, SLIP
from jarvis.core.procedures.reflect import Attempt, FailureCase

REQUEST = "Alice says Bob lies. Bob says Carol tells the truth. Does Carol tell the truth?"
CASE = FailureCase("main", "web_of_lies", (Attempt(REQUEST, "yes"),), references=("no, no, yes",))


def test_check_passes_scoped_generalized_proposals():
    assert check(PROCEDURE_FIX, CASE, room=True) is None
    assert check(PATTERN_FIX, CASE, room=True) is None
    assert check(SLIP, CASE, room=False) is None


@pytest.mark.parametrize(
    ("update", "room", "needle"),
    [
        ({"action": "task_pattern"}, True, "revise_procedure"),
        ({"content": ""}, True, "비었다"),
        ({"content": "x" * 1501}, True, "1500"),
        ({"content": "The answer is no, no, yes for this kind"}, True, "정답"),
        ({"content": f"Read: {REQUEST}"}, True, "그대로"),
        ({}, False, "상한"),
    ],
    ids=["scope_action", "empty", "too_long", "reference", "verbatim", "cap"],
)
def test_check_refuses_with_reason(update, room, needle):
    assert needle in check(PROCEDURE_FIX.model_copy(update=update), CASE, room=room)


def test_check_refuses_task_pattern_without_keywords():
    assert "keywords" in check(PATTERN_FIX.model_copy(update={"keywords": ["x"]}), CASE, room=True)


def test_leaks_reference_ignores_short_answers_and_matches_whole_words():
    assert leaks_reference("pick (b) when unsure", "b") is False
    assert leaks_reference("answer disproved here", "disproved") is True
    assert leaks_reference("undisprovedness", "disproved") is False


def test_copied_span_finds_long_verbatim_piece_only():
    assert copied_span("x " + REQUEST[:COPY_CHARS], [REQUEST]) == REQUEST[:COPY_CHARS].lower()
    assert copied_span("short text", [REQUEST]) == ""
