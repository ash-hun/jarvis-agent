"""agent_loop: run_agent_loop 의 턴 반복, 도구 실행 모드, 중단, 오류 격리, 히스토리 무결성, 사고 블록 주입."""

import pytest
import asyncio

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
from jarvis.model_layer.model_types import (
    ErrorEvent,
    ModelConfig,
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
from tests.fixtures.agent_loop_helpers import ScriptedProvider, register, text_turn, tool_turn
from jarvis.agent_layer.loop import EMPTY_REPLY_NUDGE, run_agent_loop
from jarvis.model_layer.model_registry import get_default_registry
from tests.fixtures.faux_provider import FauxProvider


def _context(model: ModelConfig, **kw) -> AgentContext:
    return AgentContext(session_id="s1", messages=[], model=model, **kw)


class Recorder:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    def of(self, kind) -> list:
        return [e for e in self.events if isinstance(e, kind)]

    @property
    def types(self) -> list[str]:
        return [type(e).__name__ for e in self.events]


async def _ok_executor(tool_call_id, tool_name, params) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text=f"{tool_name} done")]
    )


async def _deny_executor(tool_call_id, tool_name, params) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="denied")], is_error=True, denied=True
    )


async def _final_executor(tool_call_id, tool_name, params) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="표 그대로")], final=True
    )


def _kinds(context: AgentContext) -> list[str]:
    return [type(m).__name__ for m in context.messages]


async def test_single_turn_emits_lifecycle_events_in_order():
    model = register(ScriptedProvider([text_turn("안녕")]))
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(), rec)

    assert rec.types == ["AgentStartEvent", "TurnStartEvent", "MessageUpdateEvent", "AgentEndEvent"]
    assert result is not None and result.text() == "안녕"
    assert rec.of(AgentEndEvent)[0].turns == 1


async def test_agent_name_is_carried_on_start_and_end():
    model = register(ScriptedProvider([text_turn("x")]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(), rec, agent_name="researcher")

    assert rec.of(AgentStartEvent)[0].agent_name == "researcher"
    assert rec.of(AgentEndEvent)[0].agent_name == "researcher"


async def test_usage_and_thinking_are_collected():
    turn = [
        ThinkingDeltaEvent(thinking="음..."),
        TextDeltaEvent(delta="답"),
        StopEvent(reason="stop", usage=Usage(input=11, output=22)),
    ]
    model = register(ScriptedProvider([turn]))

    result = await run_agent_loop(_context(model), AgentLoopConfig(), Recorder())

    assert result is not None
    assert isinstance(result.content[0], ThinkingContent)
    assert result.usage.input == 11 and result.usage.output == 22


async def test_tool_call_turn_feeds_results_into_next_turn():
    model = register(ScriptedProvider([tool_turn(("c1", "read_file", {"path": "a"})), text_turn("끝")]))
    rec = Recorder()
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _ok_executor)

    assert result is not None and result.text() == "끝"
    assert rec.of(AgentEndEvent)[0].turns == 2
    assert _kinds(context) == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]
    assert rec.of(ToolExecutionStartEvent)[0].tool_name == "read_file"
    assert rec.of(ToolExecutionEndEvent)[0].is_error is False


async def test_all_denied_ends_turn_without_asking_model_again():
    provider = ScriptedProvider([tool_turn(("c1", "bash", {"command": "chmod 000 a.md"})), text_turn("직접 하세요")])
    rec = Recorder()
    context = _context(register(provider))

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _deny_executor)

    assert len(provider.calls) == 1
    assert result is not None
    assert result.text() == "승인이 거부되어 bash 실행을 멈췄습니다. 필요하면 다시 요청해 주세요."
    assert [m.text_delta for m in rec.of(MessageUpdateEvent)] == [result.text()]
    assert _kinds(context) == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]


async def test_timed_out_approval_says_so():
    async def timed_out(tool_call_id, tool_name, params):
        result = await _deny_executor(tool_call_id, tool_name, params)
        return result.model_copy(update={"timed_out": True})

    provider = ScriptedProvider([tool_turn(("c1", "bash", {"command": "ls"})), text_turn("직접 하세요")])

    result = await run_agent_loop(_context(register(provider)), AgentLoopConfig(), Recorder(), timed_out)

    assert result is not None
    assert result.text() == "승인 요청에 시간 안에 답이 없어 bash 실행을 멈췄습니다. 필요하면 다시 요청해 주세요."


async def test_final_result_is_the_answer_without_asking_model_again():
    provider = ScriptedProvider([tool_turn(("c1", "housing_budget", {})), text_turn("요약")])
    rec = Recorder()
    context = _context(register(provider))

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _final_executor)

    assert len(provider.calls) == 1
    assert result is not None and result.text() == "표 그대로"
    assert [m.text_delta for m in rec.of(MessageUpdateEvent)] == ["표 그대로"]
    assert _kinds(context) == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]


@pytest.mark.parametrize(
    ("special_tool", "special_executor", "answer"),
    [("bash", _deny_executor, "읽었습니다"), ("housing_budget", _final_executor, "정리")],
)
async def test_special_result_mixed_with_ok_result_lets_model_answer(special_tool, special_executor, answer):
    async def mixed(tool_call_id, tool_name, params):
        if tool_name == special_tool:
            return await special_executor(tool_call_id, tool_name, params)
        return await _ok_executor(tool_call_id, tool_name, params)

    calls = tool_turn(("c1", special_tool, {}), ("c2", "read_file", {"path": "a"}))
    provider = ScriptedProvider([calls, text_turn(answer)])

    result = await run_agent_loop(_context(register(provider)), AgentLoopConfig(), Recorder(), mixed)

    assert len(provider.calls) == 2
    assert result is not None and result.text() == answer


@pytest.mark.parametrize(
    ("turn", "executor"),
    [
        (tool_turn(("c1", "bash", {})), None),
        ([ToolCallDeltaEvent(id="c1", name="bash", arguments_delta="{}"), StopEvent(reason="stop", usage=Usage())],
         _ok_executor),
    ],
    ids=["no_executor", "stop_reason_not_tool_use"],
)
async def test_tool_calls_are_not_executed_and_loop_ends(turn, executor):
    model = register(ScriptedProvider([turn]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(), rec, executor)

    assert rec.of(ToolExecutionStartEvent) == []
    assert rec.of(AgentEndEvent)[0].turns == 1


async def test_max_turns_caps_the_loop():
    model = register(ScriptedProvider([tool_turn(("c1", "bash", {}))]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(max_turns=3), rec, _ok_executor)

    assert rec.of(AgentEndEvent)[0].turns == 3
    assert len(rec.of(TurnStartEvent)) == 3


async def test_zero_max_turns_ends_cleanly():
    model = register(ScriptedProvider([text_turn("x")]))
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(max_turns=0), rec)

    assert result is None
    assert rec.of(AgentEndEvent)[0].turns == 0


async def test_malformed_tool_arguments_fall_back_to_empty_dict():
    turn = [
        ToolCallDeltaEvent(id="c1", name="bash", arguments_delta="{not json"),
        StopEvent(reason="stop", usage=Usage()),
    ]
    model = register(ScriptedProvider([turn]))

    result = await run_agent_loop(_context(model), AgentLoopConfig(), Recorder())

    assert result is not None
    call = next(c for c in result.content if isinstance(c, ToolCall))
    assert call.arguments == {}


@pytest.mark.parametrize(("mode", "max_expected"), [("parallel", 2), ("sequential", 1)])
async def test_tool_execution_mode_controls_overlap_and_keeps_call_order(mode, max_expected):
    model = register(ScriptedProvider([tool_turn(("c1", "slow", {}), ("c2", "fast", {})), text_turn("끝")]))
    active = 0
    max_active = 0

    async def executor(tool_call_id, tool_name, params):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[])

    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(tool_execution_mode=mode), Recorder(), executor)

    assert max_active == max_expected
    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [r.tool_call_id for r in results] == ["c1", "c2"]


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
async def test_executor_exception_becomes_error_result(mode):
    model = register(ScriptedProvider([tool_turn(("c1", "boom", {})), text_turn("끝")]))

    async def boom(tool_call_id, tool_name, params):
        raise RuntimeError("tool crashed")

    rec = Recorder()
    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(tool_execution_mode=mode), rec, boom)

    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is True
    assert rec.of(ToolExecutionEndEvent)[0].is_error is True
    assert rec.of(AgentEndEvent)[0].turns == 2


async def test_cancelled_parallel_tool_becomes_error_result_and_others_continue():
    model = register(ScriptedProvider([tool_turn(("1", "slow", {}), ("2", "fast", {})), text_turn("끝")]))

    async def executor(call_id: str, name: str, args: dict) -> ToolResultMessage:
        if name == "slow":
            raise asyncio.CancelledError()
        return ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[], is_error=False)

    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(tool_execution_mode="parallel"), Recorder(), executor)

    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [(r.tool_name, r.is_error) for r in results] == [("slow", True), ("fast", False)]


async def test_signal_set_before_run_skips_all_turns():
    model = register(ScriptedProvider([text_turn("x")]))
    signal = asyncio.Event()
    signal.set()
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(), rec, signal=signal)

    assert result is None
    assert rec.of(TurnStartEvent) == []
    assert rec.of(AgentEndEvent)[0].turns == 1


async def test_signal_stops_remaining_sequential_tools():
    model = register(ScriptedProvider([tool_turn(("c1", "a", {}), ("c2", "b", {})), text_turn("끝")]))
    signal = asyncio.Event()

    async def executor(tool_call_id, tool_name, params):
        signal.set()
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[])

    rec = Recorder()

    config = AgentLoopConfig(tool_execution_mode="sequential")

    await run_agent_loop(_context(model), config, rec, executor, signal=signal)

    assert [e.tool_call_id for e in rec.of(ToolExecutionEndEvent)] == ["c1"]


async def test_stream_error_emits_agent_error_and_leaves_no_empty_assistant():
    model = register(ScriptedProvider([[ErrorEvent(message="provider down", code="e")]]))
    rec = Recorder()
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _ok_executor)

    assert rec.of(AgentErrorEvent)[0].message == "provider down"
    assert result is not None and result.text() == "" and result.error_message == "provider down"
    assert rec.of(AgentEndEvent)[0].turns == 1
    assert context.messages == []


@pytest.mark.parametrize(
    ("system_prompt", "inner_thought", "expected"),
    [
        ("너는 Jarvis다.", "[내적 사고] 사용자는 급하다", "너는 Jarvis다.\n\n[내적 사고] 사용자는 급하다"),
        (None, "블록", "블록"),
        ("기본", None, "기본"),
    ],
)
async def test_inner_thought_is_appended_to_system_prompt_only(system_prompt, inner_thought, expected):
    provider = ScriptedProvider([text_turn("답")])
    metadata = {"inner_thought_prompt": inner_thought} if inner_thought else {}
    context = _context(register(provider), system_prompt=system_prompt, metadata=metadata)

    await run_agent_loop(context, AgentLoopConfig(), Recorder())

    sent = provider.calls[0]
    assert sent.system_prompt == expected
    assert inner_thought is None or all(inner_thought not in str(getattr(m, "content", "")) for m in sent.messages)


async def test_max_turns_exhaustion_closes_dangling_tool_calls():
    """마지막 턴이 tool_use 로 끝나면 에러 tool_result 를 붙여 히스토리를 provider 가 받는 형태로 유지한다."""
    model = register(ScriptedProvider([tool_turn(("c1", "bash", {}))] * 2))
    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(max_turns=2), Recorder(), _ok_executor)

    assert _kinds(context) == ["AssistantMessage", "ToolResultMessage", "AssistantMessage", "ToolResultMessage"]


async def test_no_executor_closes_dangling_tool_calls_with_error_results():
    model = register(ScriptedProvider([tool_turn(("c1", "bash", {}), ("c2", "grep", {}))]))
    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(), Recorder(), tool_executor=None)

    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [(r.tool_call_id, r.is_error) for r in results] == [("c1", True), ("c2", True)]


async def test_empty_reply_after_tools_is_retried_once_with_a_nudge():
    empty = [StopEvent(reason="stop", usage=Usage(output=1))]
    provider = ScriptedProvider([tool_turn(("c1", "t", {})), empty, text_turn("정리한 답")])
    context = _context(register(provider))

    result = await run_agent_loop(context, AgentLoopConfig(), Recorder(), tool_executor=_ok_executor)

    assert result is not None and result.text() == "정리한 답"
    assert len(provider.calls) == 3
    assert provider.calls[2].messages[-1].content == EMPTY_REPLY_NUDGE
    # 안내 문구도, 빈 답도 대화 기록에는 남지 않는다
    assert _kinds(context) == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]


@pytest.mark.parametrize(
    ("turns", "calls"),
    [
        ([[StopEvent(reason="stop", usage=Usage())]], 1),
        ([tool_turn(("c1", "t", {})), [StopEvent(reason="stop", usage=Usage())]], 3),
    ],
    ids=["without_tools_not_retried", "second_empty_ends_turn"],
)
async def test_empty_reply_is_retried_at_most_once_and_only_after_tools(turns, calls):
    provider = ScriptedProvider(turns)

    result = await run_agent_loop(_context(register(provider)), AgentLoopConfig(), Recorder(), _ok_executor)

    assert len(provider.calls) == calls
    assert result is not None and result.text() == ""


class RecordingProvider(FauxProvider):
    def __init__(self) -> None:
        super().__init__(response="네")
        self.system_prompts: list[str | None] = []

    async def stream(self, model, context, options=None):  # type: ignore[no-untyped-def]
        self.system_prompts.append(context.system_prompt)
        async for event in super().stream(model, context, options):
            yield event


async def _noop(event) -> None:  # type: ignore[no-untyped-def]
    return None


@pytest.mark.parametrize(
    ("base", "metadata", "expected"),
    [
        (
            "기존 프롬프트",
            {"inner_thought_prompt": "[내적 사고]\n해석: 진짜 의도"},
            "기존 프롬프트\n\n[내적 사고]\n해석: 진짜 의도",
        ),
        ("P", {}, "P"),
        (None, {"inner_thought_prompt": "[내적 사고] x"}, "[내적 사고] x"),
    ],
    ids=["appends_block", "noop_without_block", "block_only_without_base"],
)
async def test_run_agent_loop_augments_system_prompt_with_thought_block(monkeypatch, base, metadata, expected):
    provider = RecordingProvider()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    context = AgentContext(
        session_id="s",
        model=ModelConfig(provider="faux", model="m"),
        messages=[UserMessage(content="안녕")],
        system_prompt=base,
        metadata=metadata,
    )

    await run_agent_loop(context, AgentLoopConfig(), _noop)

    assert provider.system_prompts == [expected]
    assert context.system_prompt == base
