"""procedures 기능의 구간 탐지: 도구를 여러 번 써서 성공한 작업 구간만 고른다."""

import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from tests.fixtures.procedures_helpers import success_history, tool_turn
from jarvis.core.procedures import find_spans


def _recovered_history() -> list:
    return [
        UserMessage(content="테스트 돌리고 요약해줘"),
        *tool_turn("c1", "glob", {"pattern": "tests/**/*.py"}),
        *tool_turn("c2", "bash", {"command": "pytest -q"}, is_error=True),
        *tool_turn("c3", "bash", {"command": "uv run pytest -q"}),
        *tool_turn("c4", "read_file", {"path": "pytest.log"}),
        AssistantMessage(content=[TextContent(text="전부 통과했습니다.")], stop_reason="stop"),
    ]


def _with_tool_error() -> list:
    history = success_history()
    history[4] = ToolResultMessage(
        tool_call_id="c2", tool_name="bash", content=[TextContent(text="boom")], is_error=True
    )
    return history


def _unrecovered() -> list:
    history = _recovered_history()
    # 실패 뒤 같은 도구가 다시 성공하지 않았으면 회복이 아니다
    return history[:3] + history[5:7] + tool_turn("c5", "bash", {"command": "x"}, is_error=True) + history[-1:]


def test_find_spans_detects_successful_multi_tool_task():
    spans = find_spans(success_history())

    assert len(spans) == 1
    span = spans[0]
    assert span.start == 0
    assert span.request == "테스트 돌리고 요약해줘"
    assert [s.name for s in span.steps] == ["glob", "bash", "read_file"]
    assert span.tool_names == ("glob", "bash", "read_file")
    assert span.outcome == "전부 통과했습니다."


@pytest.mark.parametrize(
    ("history", "min_tool_calls"),
    [
        (success_history(), 4),
        (_with_tool_error(), 3),
        (success_history()[:-1], 3),
        (_unrecovered(), 3),
    ],
    ids=["too_few_calls", "tool_error", "no_outcome", "unrecovered_failure"],
)
def test_find_spans_returns_nothing_for_short_failed_or_unfinished_task(history, min_tool_calls):
    assert find_spans(history, min_tool_calls=min_tool_calls) == []


def test_find_spans_drops_failed_call_from_recovered_task():
    [span] = find_spans(_recovered_history())

    assert [(s.name, s.args) for s in span.steps] == [
        ("glob", {"pattern": "tests/**/*.py"}),
        ("bash", {"command": "uv run pytest -q"}),
        ("read_file", {"path": "pytest.log"}),
    ]


def test_find_spans_splits_on_user_messages_and_indexes_by_start():
    history = [UserMessage(content="안녕"), AssistantMessage(content=[TextContent(text="안녕하세요")])]
    history += success_history("두 번째 작업")

    spans = find_spans(history)

    assert [(s.start, s.request) for s in spans] == [(2, "두 번째 작업")]
