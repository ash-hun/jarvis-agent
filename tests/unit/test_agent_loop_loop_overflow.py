"""agent_loop: 넘침 판단, 이어갈 예산, 이어가기 지시, 정리문 자르기와 대체 정리문."""

import pytest

from jarvis.agent_layer.loop_overflow import (
    clip_summary,
    exhausted,
    FALLBACK_HEADER,
    fallback_summary,
    FALLBACK_STEPS,
    overflow_action,
    resume_budget,
    resume_directive,
    SUMMARY_CHARS,
)
from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolCall, ToolResultMessage, UserMessage


def _call(name: str) -> AssistantMessage:
    return AssistantMessage(content=[ToolCall(id=name, name=name, arguments={})], stop_reason="tool_use")


def _result(name: str) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=name, tool_name=name, content=[TextContent(text="ok")])


def test_exhausted_when_history_ends_with_tool_result():
    assert exhausted([UserMessage(content="q"), _call("a"), _result("a")])


ANSWERED = [UserMessage(content="q"), AssistantMessage(content=[TextContent(text="답")])]


@pytest.mark.parametrize("messages", [[], ANSWERED])
def test_not_exhausted_when_answered_or_empty(messages):
    assert not exhausted(messages)


@pytest.mark.parametrize(("max_turns", "budget"), [(20, 10), (5, 2), (1, 1), (0, 1)])
def test_resume_budget_is_half_with_floor_one(max_turns, budget):
    assert resume_budget(max_turns) == budget


def test_overflow_action_resumes_once_then_answers():
    assert [overflow_action(n) for n in range(3)] == ["resume", "answer", "answer"]


def test_resume_directive_carries_budget_and_summary():
    text = resume_directive("남은 단계: 합계 구하기", 3)

    assert "3번" in text and text.endswith("남은 단계: 합계 구하기")


def test_clip_summary_cuts_long_text():
    assert clip_summary("  짧다 ") == "짧다"
    clipped = clip_summary("가" * (SUMMARY_CHARS + 50))
    assert len(clipped) == SUMMARY_CHARS + 1 and clipped.endswith("…")


def test_fallback_summary_lists_recent_tool_names():
    messages = [m for i in range(FALLBACK_STEPS + 2) for m in (_call(f"t{i}"), _result(f"t{i}"))]

    text = fallback_summary(messages)

    assert text.startswith(FALLBACK_HEADER) and "앞의 2번 생략" in text
    assert "t0," not in text and text.endswith(f"t{FALLBACK_STEPS + 1}")


def test_fallback_summary_without_tools_is_header_only():
    assert fallback_summary([UserMessage(content="q")]) == FALLBACK_HEADER.rstrip(":") + "."
