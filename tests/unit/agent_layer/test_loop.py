"""[agent_layer] run_agent_loop() 직접 테스트(턴 로직, 툴 실행 모드, 중단, 에러 격리)."""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.agent_layer.loop import _augment_system_prompt, run_agent_loop
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
from jarvis.model_layer.types import (
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
)


class ScriptedProvider:
    """호출 순서대로 미리 정한 이벤트 목록을 흘리는 프로바이더.

    턴마다 다른 응답이 필요해 FauxProvider(고정 응답) 대신 쓴다.
    """

    provider_name = "scripted"

    def __init__(self, turns: list[list]) -> None:
        self._turns = turns
        self.calls: list = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(self, model, context, options=None):
        self.calls.append(context)
        events = self._turns[min(len(self.calls) - 1, len(self._turns) - 1)]
        for event in events:
            yield event


def _register(provider: ScriptedProvider) -> ModelConfig:
    from jarvis.model_layer.registry import get_default_registry

    get_default_registry()._providers["scripted"] = provider
    return ModelConfig(provider="scripted", model="scripted-model")


def _text_turn(text: str) -> list:
    return [TextDeltaEvent(delta=text), StopEvent(reason="stop", usage=Usage(input=3, output=4))]


def _tool_turn(*calls: tuple[str, str, dict]) -> list:
    events: list = []
    for tc_id, name, args in calls:
        events.append(
            ToolCallDeltaEvent(id=tc_id, name=name, arguments_delta=json.dumps(args))
        )
    events.append(StopEvent(reason="tool_use", usage=Usage()))
    return events


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
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=[TextContent(text=f"{tool_name} done")],
    )


# ── 단일 턴 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_turn_emits_lifecycle_events_in_order():
    model = _register(ScriptedProvider([_text_turn("안녕")]))
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(), rec)

    assert rec.types == [
        "AgentStartEvent",
        "TurnStartEvent",
        "MessageUpdateEvent",
        "AgentEndEvent",
    ]
    assert result is not None and result.text() == "안녕"
    assert rec.of(AgentEndEvent)[0].turns == 1


@pytest.mark.asyncio
async def test_agent_name_is_carried_on_start_and_end():
    model = _register(ScriptedProvider([_text_turn("x")]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(), rec, agent_name="researcher")

    assert rec.of(AgentStartEvent)[0].agent_name == "researcher"
    assert rec.of(AgentEndEvent)[0].agent_name == "researcher"


@pytest.mark.asyncio
async def test_usage_and_thinking_are_collected():
    model = _register(
        ScriptedProvider([
            [
                ThinkingDeltaEvent(thinking="음..."),
                TextDeltaEvent(delta="답"),
                StopEvent(reason="stop", usage=Usage(input=11, output=22)),
            ]
        ])
    )
    result = await run_agent_loop(_context(model), AgentLoopConfig(), Recorder())

    assert result is not None
    assert isinstance(result.content[0], ThinkingContent)
    assert result.usage.input == 11 and result.usage.output == 22


# ── 멀티턴 / 툴 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_call_turn_feeds_results_into_next_turn():
    model = _register(
        ScriptedProvider([_tool_turn(("c1", "read_file", {"path": "a"})), _text_turn("끝")])
    )
    rec = Recorder()
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _ok_executor)

    assert result is not None and result.text() == "끝"
    assert rec.of(AgentEndEvent)[0].turns == 2
    # assistant(tool_use) → tool_result → assistant(text) 순으로 컨텍스트가 쌓인다.
    assert [type(m).__name__ for m in context.messages] == [
        "AssistantMessage",
        "ToolResultMessage",
        "AssistantMessage",
    ]
    assert rec.of(ToolExecutionStartEvent)[0].tool_name == "read_file"
    assert rec.of(ToolExecutionEndEvent)[0].is_error is False


async def _deny_executor(tool_call_id, tool_name, params) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="denied")], is_error=True, denied=True
    )


async def test_all_denied_ends_turn_without_asking_model_again():
    provider = ScriptedProvider([_tool_turn(("c1", "bash", {"command": "chmod 000 a.md"})), _text_turn("직접 하세요")])
    model = _register(provider)
    rec = Recorder()
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), rec, _deny_executor)

    assert len(provider.calls) == 1
    assert result is not None
    assert result.text() == "승인을 받지 못해 bash 실행을 멈췄습니다. 필요하면 다시 요청해 주세요."
    assert [m.text_delta for m in rec.of(MessageUpdateEvent)] == [result.text()]
    assert [type(m).__name__ for m in context.messages] == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]


async def test_partly_denied_lets_model_answer():
    async def mixed(tool_call_id, tool_name, params):
        if tool_name == "bash":
            return await _deny_executor(tool_call_id, tool_name, params)
        return await _ok_executor(tool_call_id, tool_name, params)

    provider = ScriptedProvider(
        [_tool_turn(("c1", "bash", {"command": "ls"}), ("c2", "read_file", {"path": "a"})), _text_turn("읽었습니다")]
    )
    result = await run_agent_loop(_context(_register(provider)), AgentLoopConfig(), Recorder(), mixed)

    assert len(provider.calls) == 2
    assert result is not None and result.text() == "읽었습니다"


@pytest.mark.asyncio
async def test_loop_stops_when_no_tool_executor():
    model = _register(ScriptedProvider([_tool_turn(("c1", "bash", {}))]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(), rec, tool_executor=None)

    assert rec.of(AgentEndEvent)[0].turns == 1
    assert rec.of(ToolExecutionStartEvent) == []


@pytest.mark.asyncio
async def test_tool_calls_without_tool_use_stop_reason_end_the_loop():
    # stop_reason이 tool_use가 아니면 tool call이 있어도 실행하지 않는다.
    events = [
        ToolCallDeltaEvent(id="c1", name="bash", arguments_delta="{}"),
        StopEvent(reason="stop", usage=Usage()),
    ]
    model = _register(ScriptedProvider([events]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(), rec, _ok_executor)

    assert rec.of(ToolExecutionStartEvent) == []
    assert rec.of(AgentEndEvent)[0].turns == 1


@pytest.mark.asyncio
async def test_max_turns_caps_the_loop():
    model = _register(ScriptedProvider([_tool_turn(("c1", "bash", {}))]))
    rec = Recorder()

    await run_agent_loop(_context(model), AgentLoopConfig(max_turns=3), rec, _ok_executor)

    assert rec.of(AgentEndEvent)[0].turns == 3
    assert len(rec.of(TurnStartEvent)) == 3


@pytest.mark.asyncio
async def test_zero_max_turns_ends_cleanly():
    model = _register(ScriptedProvider([_text_turn("x")]))
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(max_turns=0), rec)

    assert result is None
    assert rec.of(AgentEndEvent)[0].turns == 0


@pytest.mark.asyncio
async def test_malformed_tool_arguments_fall_back_to_empty_dict():
    events = [
        ToolCallDeltaEvent(id="c1", name="bash", arguments_delta="{not json"),
        StopEvent(reason="stop", usage=Usage()),
    ]
    model = _register(ScriptedProvider([events]))

    result = await run_agent_loop(_context(model), AgentLoopConfig(), Recorder())

    assert result is not None
    call = next(c for c in result.content if isinstance(c, ToolCall))
    assert call.arguments == {}


# ── 툴 실행 모드 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_mode_overlaps_tool_execution():
    model = _register(
        ScriptedProvider([
            _tool_turn(("c1", "slow", {}), ("c2", "fast", {})),
            _text_turn("끝"),
        ])
    )
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
    await run_agent_loop(context, AgentLoopConfig(tool_execution_mode="parallel"), Recorder(), executor)

    assert max_active == 2
    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [r.tool_call_id for r in results] == ["c1", "c2"]  # 호출 순서 보존


@pytest.mark.asyncio
async def test_sequential_mode_runs_one_at_a_time():
    model = _register(
        ScriptedProvider([
            _tool_turn(("c1", "a", {}), ("c2", "b", {})),
            _text_turn("끝"),
        ])
    )
    active = 0
    max_active = 0

    async def executor(tool_call_id, tool_name, params):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[])

    await run_agent_loop(
        _context(model), AgentLoopConfig(tool_execution_mode="sequential"), Recorder(), executor
    )

    assert max_active == 1


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
@pytest.mark.asyncio
async def test_executor_exception_becomes_error_result(mode):
    model = _register(
        ScriptedProvider([_tool_turn(("c1", "boom", {})), _text_turn("끝")])
    )

    async def boom(tool_call_id, tool_name, params):
        raise RuntimeError("tool crashed")

    rec = Recorder()
    context = _context(model)
    await run_agent_loop(context, AgentLoopConfig(tool_execution_mode=mode), rec, boom)

    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is True
    assert rec.of(ToolExecutionEndEvent)[0].is_error is True
    # 루프는 죽지 않고 다음 턴으로 이어진다.
    assert rec.of(AgentEndEvent)[0].turns == 2


# ── 중단 / 에러 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_set_before_run_skips_all_turns():
    model = _register(ScriptedProvider([_text_turn("x")]))
    signal = asyncio.Event()
    signal.set()
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(), rec, signal=signal)

    assert result is None
    assert rec.of(TurnStartEvent) == []
    assert rec.of(AgentEndEvent)[0].turns == 1


@pytest.mark.asyncio
async def test_signal_stops_remaining_sequential_tools():
    model = _register(
        ScriptedProvider([_tool_turn(("c1", "a", {}), ("c2", "b", {})), _text_turn("끝")])
    )
    signal = asyncio.Event()

    async def executor(tool_call_id, tool_name, params):
        signal.set()  # 첫 툴 실행 중 중단 신호
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[])

    rec = Recorder()
    await run_agent_loop(
        _context(model),
        AgentLoopConfig(tool_execution_mode="sequential"),
        rec,
        executor,
        signal=signal,
    )

    assert [e.tool_call_id for e in rec.of(ToolExecutionEndEvent)] == ["c1"]


@pytest.mark.asyncio
async def test_stream_error_emits_agent_error_and_ends():
    model = _register(ScriptedProvider([[ErrorEvent(message="provider down", code="e")]]))
    rec = Recorder()

    result = await run_agent_loop(_context(model), AgentLoopConfig(), rec, _ok_executor)

    assert rec.of(AgentErrorEvent)[0].message == "provider down"
    assert result is not None and result.text() == ""
    assert rec.of(AgentEndEvent)[0].turns == 1


# ── system prompt 증강 ───────────────────────────────────────────────────────


def test_inner_thought_block_is_appended_to_system_prompt():
    model = ModelConfig(provider="faux", model="m")
    context = AgentContext(
        session_id="s1",
        messages=[],
        model=model,
        system_prompt="너는 Jarvis다.",
        metadata={"inner_thought_prompt": "[내적 사고] 사용자는 급하다"},
    )
    assert _augment_system_prompt(context) == "너는 Jarvis다.\n\n[내적 사고] 사용자는 급하다"


def test_inner_thought_block_alone_when_no_system_prompt():
    model = ModelConfig(provider="faux", model="m")
    context = AgentContext(
        session_id="s1", messages=[], model=model, metadata={"inner_thought_prompt": "블록"}
    )
    assert _augment_system_prompt(context) == "블록"


def test_system_prompt_unchanged_without_inner_thought():
    model = ModelConfig(provider="faux", model="m")
    context = AgentContext(session_id="s1", messages=[], model=model, system_prompt="기본")
    assert _augment_system_prompt(context) == "기본"


@pytest.mark.asyncio
async def test_inner_thought_does_not_pollute_message_history():
    provider = ScriptedProvider([_text_turn("답")])
    model = _register(provider)
    context = _context(model, system_prompt="기본", metadata={"inner_thought_prompt": "블록"})

    await run_agent_loop(context, AgentLoopConfig(), Recorder())

    sent = provider.calls[0]
    assert sent.system_prompt == "기본\n\n블록"
    assert all("블록" not in str(getattr(m, "content", "")) for m in sent.messages)


# ── 히스토리 무결성 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_error_leaves_no_empty_assistant_in_context():
    model = _register(ScriptedProvider([[ErrorEvent(message="down", code="e")]]))
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), Recorder(), _ok_executor)

    assert result is not None and result.error_message == "down"
    assert context.messages == []


@pytest.mark.asyncio
async def test_max_turns_exhaustion_closes_dangling_tool_calls():
    """마지막 턴이 tool_use 로 끝나면 에러 tool_result 를 붙여 히스토리를 provider 가 받는 형태로 유지한다."""
    model = _register(ScriptedProvider([_tool_turn(("c1", "bash", {}))] * 2))
    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(max_turns=2), Recorder(), _ok_executor)

    assert [type(m).__name__ for m in context.messages] == [
        "AssistantMessage", "ToolResultMessage", "AssistantMessage", "ToolResultMessage",
    ]


@pytest.mark.asyncio
async def test_no_executor_closes_dangling_tool_calls_with_error_results():
    model = _register(ScriptedProvider([_tool_turn(("c1", "bash", {}), ("c2", "grep", {}))]))
    context = _context(model)

    await run_agent_loop(context, AgentLoopConfig(), Recorder(), tool_executor=None)

    results = [m for m in context.messages if isinstance(m, ToolResultMessage)]
    assert [(r.tool_call_id, r.is_error) for r in results] == [("c1", True), ("c2", True)]


# ── 도구 결과 뒤 빈 답 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_reply_after_tools_is_retried_once_with_a_nudge():
    from jarvis.agent_layer.loop import EMPTY_REPLY_NUDGE

    empty = [StopEvent(reason="stop", usage=Usage(output=1))]
    provider = ScriptedProvider([_tool_turn(("c1", "t", {})), empty, _text_turn("정리한 답")])
    model = _register(provider)
    context = _context(model)

    result = await run_agent_loop(context, AgentLoopConfig(), Recorder(), tool_executor=_ok_executor)

    assert result is not None and result.text() == "정리한 답"
    assert len(provider.calls) == 3
    assert provider.calls[2].messages[-1].content == EMPTY_REPLY_NUDGE
    # 안내 문구도, 빈 답도 대화 기록에는 남지 않는다
    assert [type(m).__name__ for m in context.messages] == ["AssistantMessage", "ToolResultMessage", "AssistantMessage"]


@pytest.mark.asyncio
async def test_empty_reply_without_tools_is_not_retried():
    provider = ScriptedProvider([[StopEvent(reason="stop", usage=Usage())]])
    model = _register(provider)
    await run_agent_loop(_context(model), AgentLoopConfig(), Recorder())
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_second_empty_reply_ends_the_turn():
    empty = [StopEvent(reason="stop", usage=Usage())]
    provider = ScriptedProvider([_tool_turn(("c1", "t", {})), empty, empty])
    model = _register(provider)
    result = await run_agent_loop(_context(model), AgentLoopConfig(), Recorder(), tool_executor=_ok_executor)
    assert len(provider.calls) == 3
    assert result is not None and result.text() == ""
