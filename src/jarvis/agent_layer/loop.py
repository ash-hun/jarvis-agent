"""[agent_layer] LLM 호출과 툴 실행을 max_turns 안에서 반복하는 에이전트 루프 본체."""

import json
import asyncio
from typing import Any, cast
from collections.abc import Awaitable, Callable

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
    UserMessage,
)
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

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]

# 도구 결과를 받고 빈 답으로 끝내면 한 번만 다시 묻는다. 실서버에서 gemma4:e4b 가 출력 1토큰으로 끝내
# 사용자가 도구 결과를 못 받는 것을 봤다. 이 문구는 LLM 호출에만 붙고 대화 기록에는 남지 않는다
# 승인을 받지 못한 도구만 남았을 때의 답. 모델에 다시 물으면 "직접 이렇게 하세요" 하고 방법 안내로 피한다
DENIED_REPLY = "승인이 거부되어 {tools} 실행을 멈췄습니다. 필요하면 다시 요청해 주세요."
DENIED_TIMEOUT_REPLY = "승인 요청에 시간 안에 답이 없어 {tools} 실행을 멈췄습니다. 필요하면 다시 요청해 주세요."
EMPTY_REPLY_NUDGE = "위 도구 결과를 바탕으로 사용자에게 답을 정리해 주세요. 결과에 있는 숫자와 링크를 그대로 씁니다."


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
        if _empty_after_tools(assistant_msg, context.messages) and not (signal and signal.is_set()):
            assistant_msg = await _stream_assistant(context, config, emit, signal, nudge=EMPTY_REPLY_NUDGE)
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
        if tool_results and all(r.denied for r in tool_results):
            final_message = _denied_reply(context, tool_results)
        elif tool_results and all(r.final and not r.is_error for r in tool_results):
            # 모델이 긴 표를 옮겨 적다 줄과 링크를 떨어뜨린다. 도구 글을 그대로 답으로 쓴다
            final_message = _reply(context, "\n\n".join(_text(r) for r in tool_results))
        else:
            continue
        await emit(MessageUpdateEvent(text_delta=final_message.text()))
        context.messages.append(final_message)
        break

    _close_dangling_tool_calls(context.messages)

    await emit(AgentEndEvent(
        session_id=context.session_id,
        final_message=final_message,
        turns=turn + 1,
        agent_name=agent_name,
    ))
    return final_message


def _denied_reply(context: AgentContext, results: list[ToolResultMessage]) -> AssistantMessage:
    tools = ", ".join(dict.fromkeys(r.tool_name for r in results))
    reply = DENIED_TIMEOUT_REPLY if all(r.timed_out for r in results) else DENIED_REPLY
    return _reply(context, reply.format(tools=tools))


def _reply(context: AgentContext, text: str) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)], provider=context.model.provider, model=context.model.model
    )


def _text(result: ToolResultMessage) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, TextContent))


def _empty_after_tools(message: AssistantMessage, history: list[Message]) -> bool:
    """도구 결과 바로 다음 답이 글도 도구 호출도 없이 끝났는가(오류 답은 아니다)."""
    return (
        message.error_message is None
        and not message.text().strip()
        and not message.tool_calls()
        and bool(history)
        and isinstance(history[-1], ToolResultMessage)
    )


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
    nudge: str | None = None,
) -> AssistantMessage:
    messages = context.messages if nudge is None else [*context.messages, UserMessage(content=nudge, timestamp=0)]
    llm_ctx = LLMContext(
        messages=messages,
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
            # 도구 하나가 취소돼도(CancelledError) 오류 결과로 남긴다. 프로세스 종료 신호는 그대로 올린다
            if isinstance(outcome, (KeyboardInterrupt, SystemExit)):
                raise outcome
            if isinstance(outcome, BaseException):
                result = ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=[],
                    is_error=True,
                )
            else:
                result = outcome
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
