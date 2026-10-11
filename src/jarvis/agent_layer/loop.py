"""[agent_layer] LLM 호출과 툴 실행을 max_turns 안에서 반복하는 에이전트 루프 본체."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

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
    Message,
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
    turn = -1  # max_turns=0이면 루프가 한 번도 돌지 않는다: turns=0으로 보고

    for turn in range(config.max_turns):
        if signal and signal.is_set():
            break

        await emit(TurnStartEvent(turn=turn))

        assistant_msg = await _stream_assistant(context, config, emit, signal)
        final_message = assistant_msg
        if assistant_msg.error_message is not None:
            # provider 에러: 빈 assistant 메시지를 히스토리에 남기면 다음 호출이 400으로 깨진다
            break
        context.messages.append(assistant_msg)

        tool_calls = assistant_msg.tool_calls()
        if not tool_calls or assistant_msg.stop_reason != "tool_use":
            break

        if tool_executor is None:
            break

        tool_results = await _execute_tools(tool_calls, tool_executor, config, emit, signal)
        context.messages.extend(tool_results)

    _close_dangling_tool_calls(context.messages)

    await emit(AgentEndEvent(
        session_id=context.session_id,
        final_message=final_message,
        turns=turn + 1,
        agent_name=agent_name,
    ))
    return final_message


def _close_dangling_tool_calls(messages: list[Message]) -> None:
    """마지막 assistant tool_use 중 결과가 없는 것에 에러 결과를 붙인다.

    max_turns 소진·abort·executor 부재로 루프가 끊기면 tool_use만 남는데, 그 히스토리로
    다음 호출을 하면 provider가 tool_result 누락으로 거부한다(Anthropic 400).
    """
    last_assistant = next(
        (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], AssistantMessage)),
        None,
    )
    if last_assistant is None:
        return
    answered = {
        m.tool_call_id for m in messages[last_assistant + 1 :] if isinstance(m, ToolResultMessage)
    }
    # 위 next() 가 AssistantMessage 인 위치만 골랐다
    last = cast(AssistantMessage, messages[last_assistant])
    for tc in last.tool_calls():
        if tc.id in answered:
            continue
        messages.append(ToolResultMessage(
            tool_call_id=tc.id,
            tool_name=tc.name,
            content=[TextContent(text="Tool was not executed (loop ended before execution)")],
            is_error=True,
        ))


def _augment_system_prompt(context: AgentContext) -> str | None:
    """inner thought composer가 조립한 텍스트가 있으면 system_prompt에 덧붙인다.

    조립은 session의 ThoughtComposer가 담당(교체 가능). loop는 결과 문자열만
    system_prompt에 합치며, 대화 히스토리/세션 저장은 건드리지 않아 오염을 막는다.
    """
    base = context.system_prompt
    block = context.metadata.get("inner_thought_prompt")
    if not block:
        return base
    return f"{base}\n\n{block}" if base else block


async def _stream_assistant(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: AgentEventSink,
    signal: asyncio.Event | None,
) -> AssistantMessage:
    llm_ctx = LLMContext(
        messages=context.messages,
        tools=context.tools if context.tools else None,
        system_prompt=_augment_system_prompt(context),
    )

    text_buffer = ""
    thinking_buffer = ""
    tool_buffers: dict[str, dict[str, str]] = {}
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
                error_message=event.message,
            )

    content: list[TextContent | ThinkingContent | ToolCall] = []
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
        stop_reason=stop_reason,
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
        tasks: list[Awaitable[ToolResultMessage]] = []
        for tc in tool_calls:
            await emit(ToolExecutionStartEvent(tool_call_id=tc.id, tool_name=tc.name, args=tc.arguments))
            tasks.append(executor(tc.id, tc.name, tc.arguments))
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for tc, outcome in zip(tool_calls, completed, strict=False):
            if isinstance(outcome, Exception):
                result = ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=[],
                    is_error=True,
                )
            else:
                # Exception 이 아닌 BaseException(취소 등)은 여기서 걸러지지 않는다. 기존 동작 그대로 둔다
                result = cast(ToolResultMessage, outcome)
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
