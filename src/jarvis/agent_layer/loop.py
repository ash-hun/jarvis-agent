"""[agent_layer] LLM 호출과 툴 실행을 max_turns 안에서 반복하는 에이전트 루프 본체."""

import json
import time
import asyncio
from typing import Any, cast
from collections.abc import Awaitable, Callable

from jarvis.model_layer.model_types import (
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
from jarvis.agent_layer.agent_types import (
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
from jarvis.agent_layer.loop_overflow import (
    clip_summary,
    exhausted,
    fallback_summary,
    overflow_action,
    resume_budget,
    resume_directive,
    SUMMARY_PROMPT,
)
from jarvis.agent_layer.prompt_measure import measure_prompt
from jarvis.model_layer.stream import stream
from jarvis.common.logger import get_logger

logger = get_logger(__name__)

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
    LLM 호출 → 툴 실행 → 반복. stop 이면 끝난다. max_turns 를 다 쓰고도 도구를 부르던 중이면
    정리 호출 한 번 뒤 max_turns 절반만큼 한 번 더 이어가고, 또 넘치면 정리문을 답으로 낸다.
    LLM 호출은 최대 max_turns + max_turns//2 차례(빈 답 재촉 포함 차례당 두 번)와 정리 두 번이다.
    """
    await emit(AgentStartEvent(session_id=context.session_id, prompt="", agent_name=agent_name))
    final_message: AssistantMessage | None = None
    turn = -1  # max_turns=0이면 루프가 한 번도 돌지 않는다: turns=0으로 보고
    limit = config.max_turns
    overflows = 0
    directive: str | None = None

    while True:
        start = turn + 1
        for turn in range(start, limit):
            if signal and signal.is_set():
                break

            await emit(TurnStartEvent(turn=turn))

            assistant_msg = await _stream_assistant(context, config, emit, signal, nudge=directive)
            if _empty_after_tools(assistant_msg, context.messages) and not (signal and signal.is_set()):
                nudge = EMPTY_REPLY_NUDGE if directive is None else f"{directive}\n\n{EMPTY_REPLY_NUDGE}"
                assistant_msg = await _stream_assistant(context, config, emit, signal, nudge=nudge)
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
        else:
            # 마지막 차례까지 도구를 부르고 끝났다. 끊지 않고 한 것과 남은 단계를 정리해 한 번 더 이어간다
            ready = config.overflow_resume and turn >= 0 and exhausted(context.messages)
            if ready and not (signal and signal.is_set()):
                overflows += 1
                summary = await _summarize(context, config, signal)
                if signal and signal.is_set():
                    break
                if overflow_action(overflows - 1) == "resume":
                    budget = resume_budget(config.max_turns)
                    directive = resume_directive(summary, budget)
                    limit = turn + 1 + budget
                    continue
                final_message = _reply(context, summary)
                await emit(MessageUpdateEvent(text_delta=summary))
                context.messages.append(final_message)
        break

    _close_dangling_tool_calls(context.messages)

    await emit(AgentEndEvent(
        session_id=context.session_id,
        final_message=final_message,
        turns=turn + 1,
        agent_name=agent_name,
        overflows=overflows,
    ))
    return final_message


async def _summarize(context: AgentContext, config: AgentLoopConfig, signal: asyncio.Event | None) -> str:
    """도구 없이 한 것과 남은 단계를 정리한다. 정리문은 화면에 흘리지 않고 기록에도 남기지 않는다."""

    async def _silent(_: AgentEvent) -> None:
        return None

    # ponytail: 정리 호출에 도구 정의가 없어 Anthropic 은 오류로 기본 정리문을 쓴다, 기본이 되면 tool_choice none 을
    message = await _stream_assistant(context, config, _silent, signal, nudge=SUMMARY_PROMPT, with_tools=False)
    text = message.text().strip() if message.error_message is None else ""
    return clip_summary(text) if text else fallback_summary(context.messages)


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
    with_tools: bool = True,
) -> AssistantMessage:
    messages = context.messages if nudge is None else [*context.messages, UserMessage(content=nudge, timestamp=0)]
    llm_ctx = LLMContext(
        messages=messages,
        tools=context.tools if context.tools and with_tools else None,
        system_prompt=_augment_system_prompt(context),
    )
    # 지연이 프롬프트 어느 부분에서 오는지 보려고 호출마다 부분별 크기와 첫 출력까지의 시간을 남긴다
    sizes = measure_prompt(llm_ctx, str(context.metadata.get("inner_thought_prompt") or ""))
    started = time.monotonic()
    first_output_sec: float | None = None

    text_buffer = ""
    thinking_buffer = ""
    tool_buffers: dict[str, dict[str, str]] = {}
    usage = Usage()
    stop_reason = "stop"

    async for event in stream(context.model, llm_ctx, config.stream_options):
        if signal and signal.is_set():
            break
        if first_output_sec is None and isinstance(event, (TextDeltaEvent, ThinkingDeltaEvent, ToolCallDeltaEvent)):
            first_output_sec = time.monotonic() - started

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

    logger.info(
        "[Loop] llm call",
        model=context.model.model,
        first_output_sec=None if first_output_sec is None else round(first_output_sec, 2),
        total_sec=round(time.monotonic() - started, 2),
        input_tokens=usage.input,
        cache_read=usage.cache_read,
        prompt_chars=sizes,
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
