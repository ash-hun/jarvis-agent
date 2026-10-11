"""[model_layer] vLLM 의 OpenAI 호환 SSE 스트림을 공통 스트림 이벤트로 바꾸는 프로바이더."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from jarvis.model_layer.providers.base import Provider
from jarvis.model_layer.types import (
    ErrorEvent,
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    Tool,
    ToolCallDeltaEvent,
    Usage,
)


class VLLMProvider(Provider):
    """vLLM 로컬 서버 프로바이더. OpenAI 호환 API 사용. base_url 기본값: http://localhost:8000"""

    provider_name = "vllm"

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self,
        model: ModelConfig,
        context: LLMContext,
        options: StreamOptions | None = None,
    ) -> AsyncIterator[StreamEvent]:
        base_url = (model.base_url or "http://localhost:8000").rstrip("/")
        messages = _convert_messages(context)
        tools = [_tool_to_openai(t) for t in context.tools] if context.tools else []

        payload: dict[str, Any] = {
            "model": model.model,
            "messages": messages,
            "temperature": model.temperature,
            "max_tokens": model.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {}
        if model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client, client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                tool_buffers: dict[int, dict[str, Any]] = {}
                usage = Usage()

                async for line in resp.aiter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]

                    chunk = json.loads(line)

                    if "usage" in chunk and chunk["usage"]:
                        u = chunk["usage"]
                        usage = Usage(
                            input=u.get("prompt_tokens", 0),
                            output=u.get("completion_tokens", 0),
                        )

                    if not chunk.get("choices"):
                        continue

                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})

                    if content := delta.get("content"):
                        yield TextDeltaEvent(delta=content)

                    if tcs := delta.get("tool_calls"):
                        for tc in tcs:
                            idx = tc.get("index", 0)
                            if idx not in tool_buffers:
                                tool_buffers[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_buffers[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_buffers[idx]["args"] += fn["arguments"]
                                yield ToolCallDeltaEvent(
                                    id=tool_buffers[idx]["id"],
                                    name=tool_buffers[idx]["name"],
                                    arguments_delta=fn["arguments"],
                                )

                    if finish := choice.get("finish_reason"):
                        stop_map = {"stop": "stop", "length": "length", "tool_calls": "tool_use"}
                        yield StopEvent(reason=stop_map.get(finish, "stop"), usage=usage)

        except httpx.HTTPError as exc:
            yield ErrorEvent(message=str(exc))


def _convert_messages(context: LLMContext) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if context.system_prompt:
        result.append({"role": "system", "content": context.system_prompt})

    for msg in context.messages:
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else " ".join(
                b.text for b in msg.content if b.type == "text"
            )
            result.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            text = "".join(b.text for b in msg.content if b.type == "text")
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            tool_calls = [b for b in msg.content if b.type == "tool_call"]
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


def _tool_to_openai(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
