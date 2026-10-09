from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

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


class OllamaProvider:
    """Ollama 로컬 모델 프로바이더. base_url 기본값: http://localhost:11434"""

    provider_name = "ollama"

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
        base_url = (model.base_url or "http://localhost:11434").rstrip("/")
        messages = _convert_messages(context)
        tools = [_tool_to_ollama(t) for t in context.tools] if context.tools else []

        payload: dict = {
            "model": model.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": model.temperature,
                "num_predict": model.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client:
                async with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    tool_buffers: dict[str, dict] = {}

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})

                        if content := msg.get("content"):
                            yield TextDeltaEvent(delta=content)

                        if tool_calls := msg.get("tool_calls"):
                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                name = fn.get("name", "")
                                args = json.dumps(fn.get("arguments", {}))
                                tc_id = tc.get("id", name)
                                tool_buffers[tc_id] = {"id": tc_id, "name": name}
                                yield ToolCallDeltaEvent(
                                    id=tc_id,
                                    name=name,
                                    arguments_delta=args,
                                )

                        if chunk.get("done"):
                            usage = Usage(
                                input=chunk.get("prompt_eval_count", 0),
                                output=chunk.get("eval_count", 0),
                            )
                            yield StopEvent(reason="stop", usage=usage)

        except httpx.HTTPError as exc:
            yield ErrorEvent(message=str(exc))


def _convert_messages(context: LLMContext) -> list[dict]:
    result = []
    if context.system_prompt:
        result.append({"role": "system", "content": context.system_prompt})

    for msg in context.messages:
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else _content_to_api(msg.content)
            result.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            text = "".join(b.text for b in msg.content if b.type == "text")  # type: ignore[union-attr]
            entry: dict = {"role": "assistant", "content": text}
            tool_calls = [b for b in msg.content if b.type == "tool_call"]
            if tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": tc.id, "arguments": tc.arguments}}  # type: ignore[union-attr]
                    for tc in tool_calls
                ]
            result.append(entry)

        elif msg.role == "tool_result":
            result.append({
                "role": "tool",
                "content": "\n".join(c.text for c in msg.content if hasattr(c, "text")),
            })

    return result


def _content_to_api(content: list) -> str:
    return " ".join(block.text for block in content if block.type == "text")


def _tool_to_ollama(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
