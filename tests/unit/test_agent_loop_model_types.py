"""agent_loop: 메시지와 이벤트 타입의 고정 종류, 글과 도구 호출 꺼내기, 사용량 합, JSON 왕복을 검증한다."""

import pytest

from jarvis.model_layer.model_types import (
    AssistantMessage,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


@pytest.mark.parametrize(
    ("obj", "field", "expected"),
    [
        (UserMessage(content="Hello!"), "role", "user"),
        (ToolResultMessage(tool_call_id="call_01", tool_name="bash", content=[TextContent(text="file.txt")]),
         "role", "tool_result"),
        (TextDeltaEvent(delta="hello"), "type", "text_delta"),
    ],
)
def test_type_has_fixed_kind(obj, field, expected):
    assert getattr(obj, field) == expected


@pytest.mark.parametrize("content", ["Hello!", [TextContent(text="Hello"), TextContent(text=" World")]])
def test_user_message_keeps_str_or_blocks_and_stamps_time(content):
    msg = UserMessage(content=content)

    assert msg.content == content
    assert msg.timestamp > 0


@pytest.mark.parametrize(
    ("content", "text", "tool_names"),
    [
        ([TextContent(text="Hello"), TextContent(text=" World")], "Hello World", []),
        ([ToolCall(id="call_01", name="bash", arguments={"command": "ls"})], "", ["bash"]),
        (
            [
                ThinkingContent(thinking="Let me think..."),
                TextContent(text="The answer is 42"),
                ToolCall(id="c1", name="search", arguments={"q": "42"}),
            ],
            "The answer is 42",
            ["search"],
        ),
    ],
    ids=["text_only", "tool_only", "mixed"],
)
def test_assistant_message_splits_text_and_tool_calls(content, text, tool_names):
    msg = AssistantMessage(content=content)

    assert msg.text() == text
    assert [tc.name for tc in msg.tool_calls()] == tool_names


def test_usage_total():
    assert Usage(input=100, output=50).total == 150


@pytest.mark.parametrize(
    "original",
    [
        UserMessage(content="Round-trip test"),
        AssistantMessage(
            content=[TextContent(text="Hello"), ToolCall(id="c1", name="bash", arguments={})],
            provider="faux",
            model="faux-model",
            usage=Usage(input=10, output=5),
            stop_reason="tool_use",
        ),
    ],
    ids=["user", "assistant"],
)
def test_message_roundtrips_through_json(original):
    restored = type(original).model_validate_json(original.model_dump_json())

    assert restored == original
