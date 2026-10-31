"""memory 기능의 최근 턴 창: 사용자 발화 경계에서 자르고 tool 짝을 통째로 남긴다."""

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from jarvis.memory.working.window import cut_at_user_boundary, last_turns


def _u(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _a(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


def _t(text: str) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id="c", tool_name="bash", content=[TextContent(text=text)])


def test_cut_at_user_boundary_drops_orphaned_tool_results():
    msgs = [_t("orphan"), _a("a"), _u("q"), _a("r")]

    assert cut_at_user_boundary(msgs) == msgs[2:]
    assert cut_at_user_boundary([_a("only")]) == [_a("only")]


def test_last_turns_keeps_whole_turns_with_tool_pairs():
    msgs = [_u("1"), _a("r1"), _u("2"), _a("call"), _t("out"), _a("r2"), _u("3"), _a("r3"), _u("4")]

    assert last_turns(msgs, 3) == msgs[2:]
    assert last_turns(msgs, 10) == msgs
    assert last_turns([_t("orphan"), _u("1")], 3) == [_u("1")]
