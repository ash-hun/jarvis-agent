"""model_layer/types.py: 핵심 타입 직렬화/역직렬화 테스트."""
from jarvis.model_layer.types import (
    AssistantMessage,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def test_user_message_str_content():
    msg = UserMessage(content="Hello!")
    assert msg.role == "user"
    assert msg.content == "Hello!"
    assert msg.timestamp > 0


def test_user_message_list_content():
    msg = UserMessage(content=[TextContent(text="Hello"), TextContent(text=" World")])
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2


def test_assistant_message_text_helper():
    msg = AssistantMessage(
        content=[TextContent(text="Hello"), TextContent(text=" World")]
    )
    assert msg.text() == "Hello World"


def test_assistant_message_tool_calls():
    tc = ToolCall(id="call_01", name="bash", arguments={"command": "ls"})
    msg = AssistantMessage(content=[tc])
    assert len(msg.tool_calls()) == 1
    assert msg.tool_calls()[0].name == "bash"


def test_assistant_message_mixed_content():
    msg = AssistantMessage(
        content=[
            ThinkingContent(thinking="Let me think..."),
            TextContent(text="The answer is 42"),
            ToolCall(id="c1", name="search", arguments={"q": "42"}),
        ]
    )
    assert msg.text() == "The answer is 42"
    assert len(msg.tool_calls()) == 1


def test_tool_result_message():
    result = ToolResultMessage(
        tool_call_id="call_01",
        tool_name="bash",
        content=[TextContent(text="file.txt")],
        is_error=False,
    )
    assert result.role == "tool_result"
    assert result.is_error is False


def test_usage_total():
    usage = Usage(input=100, output=50)
    assert usage.total == 150


def test_message_serialization_roundtrip():
    original = UserMessage(content="Round-trip test")
    json_str = original.model_dump_json()
    restored = UserMessage.model_validate_json(json_str)
    assert restored.content == original.content
    assert restored.timestamp == original.timestamp


def test_assistant_message_serialization_roundtrip():
    original = AssistantMessage(
        content=[TextContent(text="Hello"), ToolCall(id="c1", name="bash", arguments={})],
        provider="faux",
        model="faux-model",
        usage=Usage(input=10, output=5),
        stop_reason="tool_use",
    )
    restored = AssistantMessage.model_validate_json(original.model_dump_json())
    assert restored.text() == "Hello"
    assert len(restored.tool_calls()) == 1
    assert restored.stop_reason == "tool_use"


def test_stream_event_types():
    event = TextDeltaEvent(delta="hello")
    assert event.type == "text_delta"
    assert event.delta == "hello"
