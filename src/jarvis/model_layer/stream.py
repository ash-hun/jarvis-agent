"""[model_layer] 레지스트리에서 프로바이더를 골라 스트리밍하고 결과를 메시지로 모은다."""

from __future__ import annotations

from collections.abc import AsyncIterator

from jarvis.model_layer.registry import get_default_registry
from jarvis.model_layer.types import (
    AssistantMessage,
    LLMContext,
    ModelConfig,
    StopReason,
    StreamEvent,
    StreamOptions,
    TextContent,
    ThinkingContent,
    ToolCall,
)


async def stream(
    model: ModelConfig,
    context: LLMContext,
    options: StreamOptions | None = None,
) -> AsyncIterator[StreamEvent]:
    """주어진 ModelConfig와 LLMContext로 스트리밍 이벤트를 생성한다(Pi 의 stream() 진입점과 같은 역할)."""
    registry = get_default_registry()
    provider = registry.get(model.provider)
    async for event in provider.stream(model, context, options):
        yield event


async def stream_to_message(
    model: ModelConfig,
    context: LLMContext,
    options: StreamOptions | None = None,
) -> AssistantMessage:
    """스트림을 소비하여 완성된 AssistantMessage로 반환."""
    from jarvis.model_layer.types import (
        ErrorEvent,
        StopEvent,
        TextDeltaEvent,
        ThinkingDeltaEvent,
        ToolCallDeltaEvent,
        Usage,
    )

    text_buffer = ""
    thinking_buffer = ""
    tool_buffers: dict[str, dict[str, str]] = {}
    usage: Usage | None = None
    stop_reason: StopReason = "stop"
    error_msg: str | None = None

    async for event in stream(model, context, options):
        if isinstance(event, TextDeltaEvent):
            text_buffer += event.delta
        elif isinstance(event, ThinkingDeltaEvent):
            thinking_buffer += event.thinking
        elif isinstance(event, ToolCallDeltaEvent):
            if event.id not in tool_buffers:
                tool_buffers[event.id] = {"name": event.name, "arguments": ""}
            tool_buffers[event.id]["arguments"] += event.arguments_delta
            if event.name:
                tool_buffers[event.id]["name"] = event.name
        elif isinstance(event, StopEvent):
            stop_reason = event.reason
            usage = event.usage
        elif isinstance(event, ErrorEvent):
            error_msg = event.message
            break

    content: list[TextContent | ThinkingContent | ToolCall] = []
    if thinking_buffer:
        content.append(ThinkingContent(thinking=thinking_buffer))
    if text_buffer:
        content.append(TextContent(text=text_buffer))
    for tc_id, tc_data in tool_buffers.items():
        import json
        try:
            args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
        except json.JSONDecodeError:
            args = {}
        content.append(ToolCall(id=tc_id, name=tc_data["name"], arguments=args))

    return AssistantMessage(
        content=content,
        provider=model.provider,
        model=model.model,
        usage=usage or Usage(),
        stop_reason=stop_reason,
        error_message=error_msg,
    )
