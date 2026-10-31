"""[model_layer] Ollama /api/chat NDJSON 스트림을 공통 스트림 이벤트로 바꾸는 프로바이더."""

import json
import httpx
from typing import Any
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import (
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
    ThinkingDeltaEvent,
    Tool,
    ToolCallDeltaEvent,
    Usage,
)
from jarvis.model_layer.providers.provider_base import Provider


class OllamaProvider(Provider):
    """Ollama 로컬 모델 프로바이더. base_url 기본값: http://localhost:11434"""

    provider_name = "ollama"

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
        base_url = (model.base_url or "http://localhost:11434").rstrip("/")
        messages = _convert_messages(context)
        tools = [_tool_to_ollama(t) for t in context.tools] if context.tools else []

        payload: dict[str, Any] = {
            "model": model.model,
            "messages": messages,
            "stream": True,
            # 생각하는 모델(qwen3 계열)은 기본값이 think=on 이라 num_predict 를 전부 thinking 에 쓰고 content 가 빈다.
            # 그래서 호출자가 enable_thinking 으로 켤 때만 생각하고, 켜면 생각 과정을 thinking 델타로 넘긴다
            "think": bool(options and options.enable_thinking),
            "options": {
                "temperature": model.temperature,
                "num_predict": model.max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        if options and options.json_schema:
            # 작은 모델은 사고 프레임 JSON 을 자주 깨뜨린다. 스키마를 못 받는 모델은 501 이고 호출자가 생략 처리한다
            payload["format"] = options.json_schema

        try:
            async with httpx.AsyncClient(timeout=model.timeout) as client:
                async with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    tool_buffers: dict[str, dict[str, Any]] = {}

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})

                        if thinking := msg.get("thinking"):
                            yield ThinkingDeltaEvent(thinking=thinking)

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


def _stop_reason(chunk: dict[str, Any], had_tool_calls: bool) -> StopReason:
    if had_tool_calls:
        return "tool_use"
    return "length" if chunk.get("done_reason") == "length" else "stop"


def _convert_messages(context: LLMContext) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if context.system_prompt:
        result.append({"role": "system", "content": context.system_prompt})

    for msg in context.messages:
        if msg.role == "user":
            content = msg.content if isinstance(msg.content, str) else _content_to_api(msg.content)
            result.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            text = "".join(b.text for b in msg.content if b.type == "text")
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            tool_calls = [b for b in msg.content if b.type == "tool_call"]
            if tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in tool_calls
                ]
            result.append(entry)

        elif msg.role == "tool_result":
            result.append({
                "role": "tool",
                "content": "\n".join(c.text for c in msg.content if hasattr(c, "text")),
            })

    return result


def _content_to_api(content: list[TextContent | ImageContent]) -> str:
    return " ".join(block.text for block in content if block.type == "text")


def _tool_to_ollama(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
