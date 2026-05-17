from __future__ import annotations

import json
from typing import AsyncIterator

import anthropic

from jarvis.model_layer.types import (
    ErrorEvent,
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    Usage,
)


class AnthropicProvider:
    provider_name = "anthropic"

    def supports_thinking(self) -> bool:
        return True

    def supports_images(self) -> bool:
        return True

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        opts = options or StreamOptions()
        client = anthropic.AsyncAnthropic(
            api_key=model.api_key,
            timeout=model.timeout,
        )

        messages = _convert_messages(context)
        tools = [t.to_llm_schema() for t in context.tools] if context.tools else []

        kwargs: dict = {
            "model": model.model,
            "max_tokens": model.max_tokens,
            "messages": messages,
            "temperature": model.temperature,
        }
        if context.system_prompt:
            kwargs["system"] = context.system_prompt
        if tools:
            kwargs["tools"] = tools
        if opts.enable_thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": opts.thinking_budget}
            kwargs.pop("temperature", None)

        try:
            async with client.messages.stream(**kwargs) as stream_ctx:
                tool_buffers: dict[int, dict] = {}

                async for event in stream_ctx:
                    event_type = type(event).__name__

                    if event_type == "RawContentBlockStartEvent":
                        block = event.content_block
                        if hasattr(block, "type"):
                            if block.type == "tool_use":
                                tool_buffers[event.index] = {
                                    "id": block.id,
                                    "name": block.name,
                                    "arguments": "",
                                }

                    elif event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        delta_type = type(delta).__name__

                        if delta_type == "TextDelta":
                            yield TextDeltaEvent(delta=delta.text)
                        elif delta_type == "ThinkingDelta":
                            yield ThinkingDeltaEvent(thinking=delta.thinking)
                        elif delta_type == "InputJSONDelta":
                            if event.index in tool_buffers:
                                buf = tool_buffers[event.index]
                                buf["arguments"] += delta.partial_json
                                yield ToolCallDeltaEvent(
                                    id=buf["id"],
                                    name=buf["name"],
                                    arguments_delta=delta.partial_json,
                                )

                    elif event_type == "RawMessageStopEvent":
                        pass

                final = await stream_ctx.get_final_message()
                usage = Usage(
                    input=final.usage.input_tokens,
                    output=final.usage.output_tokens,
                    cache_read=getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                    cache_write=getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
                )
                stop_map = {
                    "end_turn": "stop",
                    "max_tokens": "length",
                    "tool_use": "tool_use",
                    "stop_sequence": "stop",
                }
                reason = stop_map.get(str(final.stop_reason), "stop")
                yield StopEvent(reason=reason, usage=usage)  # type: ignore[arg-type]

        except anthropic.APIError as exc:
            yield ErrorEvent(message=str(exc), code=str(getattr(exc, "status_code", None)))


def _convert_messages(context: LLMContext) -> list[dict]:
    result = []
    for msg in context.messages:
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else _content_to_api(msg.content)
            result.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            parts: list[dict] = []
            for block in msg.content:
                if block.type == "text":
                    parts.append({"type": "text", "text": block.text})
                elif block.type == "thinking":
                    parts.append({"type": "thinking", "thinking": block.thinking})
                elif block.type == "tool_call":
                    parts.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.arguments,
                    })
            result.append({"role": "assistant", "content": parts})

        elif msg.role == "tool_result":
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": [{"type": "text", "text": c.text} for c in msg.content if hasattr(c, "text")],
                    "is_error": msg.is_error,
                }],
            })

    return result


def _content_to_api(content: list) -> list[dict]:
    result = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "image":
            result.append({
                "type": "image",
                "source": {"type": "base64", "media_type": block.mime_type, "data": block.data},
            })
    return result
