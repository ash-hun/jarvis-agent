from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from jarvis.model_layer.types import (
    ErrorEvent,
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    Usage,
)


class GeminiProvider:
    provider_name = "gemini"

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
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError:
            yield ErrorEvent(
                message="google-genai not installed. Run: uv sync --extra gemini",
                code="import_error",
            )
            return

        client = genai.Client(api_key=model.api_key or "")
        messages = _convert_messages(context)

        config_kwargs: dict[str, Any] = {
            "temperature": model.temperature,
            "max_output_tokens": model.max_tokens,
        }
        if context.system_prompt:
            config_kwargs["system_instruction"] = context.system_prompt
        if context.tools:
            config_kwargs["tools"] = [
                genai_types.Tool(function_declarations=[
                    genai_types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters=t.parameters,
                    )
                    for t in context.tools
                ])
            ]

        generate_config = genai_types.GenerateContentConfig(**config_kwargs)

        try:
            tool_call_counter = 0
            has_tool_calls = False
            usage = Usage()
            last_finish_reason = "stop"

            async for chunk in client.aio.models.generate_content_stream(
                model=model.model,
                contents=messages,
                config=generate_config,
            ):
                if chunk.usage_metadata:
                    usage = Usage(
                        input=chunk.usage_metadata.prompt_token_count or 0,
                        output=chunk.usage_metadata.candidates_token_count or 0,
                    )

                if not chunk.candidates:
                    continue

                candidate = chunk.candidates[0]

                if candidate.finish_reason:
                    fr_name = (
                        candidate.finish_reason.name
                        if hasattr(candidate.finish_reason, "name")
                        else str(candidate.finish_reason)
                    )
                    last_finish_reason = {
                        "STOP": "stop",
                        "MAX_TOKENS": "length",
                        "SAFETY": "stop",
                    }.get(fr_name, "stop")

                if not candidate.content or not candidate.content.parts:
                    continue

                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        yield TextDeltaEvent(delta=part.text)
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        call_id = f"gemini_call_{tool_call_counter}"
                        tool_call_counter += 1
                        has_tool_calls = True
                        yield ToolCallDeltaEvent(
                            id=call_id,
                            name=fc.name,
                            arguments_delta=json.dumps(dict(fc.args) if fc.args else {}),
                        )

            reason = "tool_use" if has_tool_calls else last_finish_reason
            yield StopEvent(reason=reason, usage=usage)

        except Exception as exc:
            yield ErrorEvent(message=str(exc), code="gemini_error")


def _convert_messages(context: LLMContext) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for msg in context.messages:
        if msg.role == "user":
            if isinstance(msg.content, str):
                parts: list[dict[str, Any]] = [{"text": msg.content}]
            else:
                parts = []
                for block in msg.content:
                    if block.type == "text":
                        parts.append({"text": block.text})
                    elif block.type == "image":
                        parts.append({
                            "inline_data": {
                                "mime_type": block.mime_type,
                                "data": block.data,
                            }
                        })
            result.append({"role": "user", "parts": parts})

        elif msg.role == "assistant":
            parts = []
            for block in msg.content:
                if block.type == "text":
                    parts.append({"text": block.text})
                elif block.type == "tool_call":
                    parts.append({
                        "function_call": {
                            "name": block.name,
                            "args": block.arguments,
                        }
                    })
            if parts:
                result.append({"role": "model", "parts": parts})

        elif msg.role == "tool_result":
            content_text = "\n".join(c.text for c in msg.content if hasattr(c, "text"))
            response_data: dict[str, Any] = {"result": content_text}
            if msg.is_error:
                response_data["error"] = content_text
            result.append({
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": msg.tool_name,
                        "response": response_data,
                    }
                }],
            })

    return result
