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
            # 생각하는 모델(qwen3 계열)은 기본값이 think=on 이라 num_predict 를 전부 thinking 에 쓰고 content 가 빈다.
            # ponytail: thinking 델타를 버리므로 끈다, 사고 과정을 보여줄 때 supports_thinking 과 함께 켠다
            "think": bool(options and options.enable_thinking),
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
                            # 도구 호출이 있었는데 "stop" 으로 끝내면 루프가 도구를 실행하지 않고 빈 답으로 끝난다
                            yield StopEvent(reason=_stop_reason(chunk, bool(tool_buffers)), usage=usage)

        except httpx.HTTPError as exc:
            yield ErrorEvent(message=str(exc))


def _stop_reason(chunk: dict, had_tool_calls: bool) -> str:
    if had_tool_calls:
        return "tool_use"
    return "length" if chunk.get("done_reason") == "length" else "stop"


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
                    {"function": {"name": tc.name, "arguments": tc.arguments}}  # type: ignore[union-attr]
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
