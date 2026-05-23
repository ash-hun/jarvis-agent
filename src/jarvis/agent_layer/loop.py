from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.agent_layer.types import (
    AgentContext,
    AgentEndEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentLoopConfig,
    AgentStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnStartEvent,
)
from jarvis.model_layer.stream import stream
from jarvis.model_layer.types import (
    AssistantMessage,
    ErrorEvent,
    LLMContext,
    StopEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolResultMessage,
    Usage,
)

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]


async def run_agent_loop(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    tool_executor: Callable[[str, str, dict[str, Any]], Awaitable[ToolResultMessage]] | None = None,
    signal: asyncio.Event | None = None,
    agent_name: str | None = None,
) -> AssistantMessage | None:
    """
    Pi: runAgentLoop() 패턴.
    LLM 호출 → 툴 실행 → 반복. max_turns 초과 또는 stop 시 종료.
    """
    await emit(AgentStartEvent(session_id=context.session_id, prompt="", agent_name=agent_name))
    final_message: AssistantMessage | None = None

    for turn in range(config.max_turns):
        if signal and signal.is_set():
            break

        await emit(TurnStartEvent(turn=turn))

        assistant_msg = await _stream_assistant(context, config, emit, signal)
        context.messages.append(assistant_msg)
        final_message = assistant_msg

        tool_calls = assistant_msg.tool_calls()
        if not tool_calls or assistant_msg.stop_reason != "tool_use":
            break

        if tool_executor is None:
            break

        tool_results = await _execute_tools(tool_calls, tool_executor, config, emit, signal)
        context.messages.extend(tool_results)

    await emit(AgentEndEvent(
        session_id=context.session_id,
        final_message=final_message,
        turns=turn + 1,
        agent_name=agent_name,
    ))
    return final_message


async def _stream_assistant(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: asyncio.Event | None,
) -> AssistantMessage:
    llm_ctx = LLMContext(
        messages=context.messages,
        tools=context.tools if context.tools else None,
        system_prompt=context.system_prompt,
    )

    text_buffer = ""
    thinking_buffer = ""
    tool_buffers: dict[str, dict] = {}
    usage = Usage()
    stop_reason = "stop"

    async for event in stream(context.model, llm_ctx, config.stream_options):
        if signal and signal.is_set():
            break

        if isinstance(event, TextDeltaEvent):
            text_buffer += event.delta
            await emit(MessageUpdateEvent(text_delta=event.delta))
        elif isinstance(event, ThinkingDeltaEvent):
            thinking_buffer += event.thinking
            await emit(MessageUpdateEvent(thinking_delta=event.thinking))
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
            await emit(AgentErrorEvent(message=event.message))
            return AssistantMessage(
                content=[],
                provider=context.model.provider,
                model=context.model.model,
                usage=Usage(),
                stop_reason="stop",
            )

    content = []
    if thinking_buffer:
        content.append(ThinkingContent(thinking=thinking_buffer))
    if text_buffer:
        content.append(TextContent(text=text_buffer))
    for tc_id, tc_data in tool_buffers.items():
        try:
            args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
        except json.JSONDecodeError:
            args = {}
        content.append(ToolCall(id=tc_id, name=tc_data["name"], arguments=args))

    return AssistantMessage(
        content=content,
        provider=context.model.provider,
        model=context.model.model,
        usage=usage,
        stop_reason=stop_reason,  # type: ignore[arg-type]
    )


async def _execute_tools(
    tool_calls: list[ToolCall],
    executor: Callable[[str, str, dict[str, Any]], Awaitable[ToolResultMessage]],
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: asyncio.Event | None,
) -> list[ToolResultMessage]:
    results: list[ToolResultMessage] = []

    if config.tool_execution_mode == "parallel":
        tasks = []
        for tc in tool_calls:
            await emit(ToolExecutionStartEvent(tool_call_id=tc.id, tool_name=tc.name, args=tc.arguments))
            tasks.append(executor(tc.id, tc.name, tc.arguments))
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for tc, result in zip(tool_calls, completed, strict=False):
            if isinstance(result, Exception):
                result = ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=[],
                    is_error=True,
                )
            await emit(ToolExecutionEndEvent(tool_call_id=tc.id, tool_name=tc.name, is_error=result.is_error))
            results.append(result)
    else:
        for tc in tool_calls:
            if signal and signal.is_set():
                break
            await emit(ToolExecutionStartEvent(tool_call_id=tc.id, tool_name=tc.name, args=tc.arguments))
            try:
                result = await executor(tc.id, tc.name, tc.arguments)
            except Exception:
                result = ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=[],
                    is_error=True,
                )
            await emit(ToolExecutionEndEvent(tool_call_id=tc.id, tool_name=tc.name, is_error=result.is_error))
            results.append(result)

    return results
