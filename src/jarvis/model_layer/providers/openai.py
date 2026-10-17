"""[model_layer] OpenAI Chat Completions 스트리밍을 공통 스트림 이벤트로 바꾸는 프로바이더."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import openai as openai_sdk

from jarvis.model_layer.providers.base import Provider
from jarvis.model_layer.types import (
    ErrorEvent,
    ImageContent,
    LLMContext,
    ModelConfig,
    StopEvent,
    StopReason,
    StreamEvent,
    StreamOptions,
    TextContent,
    TextDeltaEvent,
    Tool,
    ToolCallDeltaEvent,
    Usage,
)


class OpenAIProvider(Provider):
    provider_name = "openai"

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return True

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        client = openai_sdk.AsyncOpenAI(
            api_key=model.api_key,
            # 빈 문자열을 그대로 넘기면 SDK 가 기본 주소 대신 "" 로 요청해 연결 오류가 난다
            base_url=model.base_url or None,
            timeout=model.timeout,
        )

        messages = _convert_messages(context)
        tools = [_tool_to_openai(t) for t in context.tools] if context.tools else []

        kwargs: dict[str, Any] = {
            "model": model.model,
            "messages": messages,
            "temperature": model.temperature,
            "max_tokens": model.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            tool_buffers: dict[int, dict[str, Any]] = {}
            usage = Usage()
            reason: StopReason | None = None

            async with await client.chat.completions.create(**kwargs) as stream_ctx:
                async for chunk in stream_ctx:
                    if not chunk.choices:
                        if chunk.usage:
                            usage = Usage(
                                input=chunk.usage.prompt_tokens,
                                output=chunk.usage.completion_tokens,
                            )
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    if delta.content:
                        yield TextDeltaEvent(delta=delta.content)

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_buffers:
                                tool_buffers[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                            if tc.function:
                                if tc.function.name:
                                    tool_buffers[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_buffers[idx]["arguments"] += tc.function.arguments
                                    yield ToolCallDeltaEvent(
                                        id=tool_buffers[idx]["id"],
                                        name=tool_buffers[idx]["name"],
                                        arguments_delta=tc.function.arguments,
                                    )

                    if choice.finish_reason:
                        stop_map: dict[str, StopReason] = {
                            "stop": "stop",
                            "length": "length",
                            "tool_calls": "tool_use",
                        }
                        reason = stop_map.get(choice.finish_reason, "stop")

            # 사용량은 finish_reason 뒤에 choices 가 빈 마지막 조각으로 온다. 끝까지 읽고 멈춤을 알린다
            if reason is not None:
                yield StopEvent(reason=reason, usage=usage)

        except openai_sdk.APIError as exc:
            yield ErrorEvent(message=str(exc), code=str(getattr(exc, "status_code", None)))


def _convert_messages(context: LLMContext) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if context.system_prompt:
        result.append({"role": "system", "content": context.system_prompt})

    for msg in context.messages:
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else _content_to_api(msg.content)
            result.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            text_parts = [b for b in msg.content if b.type == "text"]
            tool_calls = [b for b in msg.content if b.type == "tool_call"]
            entry: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                entry["content"] = "".join(b.text for b in text_parts)
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in tool_calls
                ]
            result.append(entry)

        elif msg.role == "tool_result":
            result.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": "\n".join(c.text for c in msg.content if hasattr(c, "text")),
            })

    return result


def _content_to_api(content: list[TextContent | ImageContent]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "image":
            result.append({
                "type": "image_url",
                "image_url": {"url": f"data:{block.mime_type};base64,{block.data}"},
            })
    return result


def _tool_to_openai(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
