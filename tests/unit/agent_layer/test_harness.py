"""[agent_layer] AgentHarness 직접 테스트(작업 기억 변환, 세션 영속, 이벤트 구독, 중단)."""

import pytest

from jarvis.agent_layer.types import (
    AgentEndEvent,
    AgentEvent,
    AgentLoopConfig,
    AgentStartEvent,
    InnerThoughtEvent,
)
from jarvis.model_layer.types import (
    Message,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from jarvis.agent_layer.harness import AgentHarness


class SpyMemory:
    """observe 호출을 기록하고 컨텍스트를 변형하는 MemoryService 대역."""

    def __init__(self, prefix: str | None = None) -> None:
        self.transform_calls: list[dict] = []
        self._prefix = prefix

    async def observe(self, messages: list[Message], context: dict) -> list[Message]:
        self.transform_calls.append(dict(context))
        if self._prefix is None:
            return messages
        return [UserMessage(content=self._prefix), *messages]

    async def reinforce(self, answer: str, context: dict, *, tools=(), failed: bool = False, steps=()) -> list[str]:
        self.reinforced = (answer, list(tools), failed)
        self.steps = list(steps)
        return []


@pytest.fixture
async def repo(jsonl_repo):
    await jsonl_repo.create(session_id="s1")
    return jsonl_repo


def _harness(model, repo, memory=None, **kw) -> AgentHarness:
    return AgentHarness(
        model=model,
        session_id="s1",
        memory=memory,
        session_repo=repo,
        **kw,
    )


# ── 세션 영속 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_persists_user_and_assistant_messages(faux_model_with_response, repo):
    model = faux_model_with_response("응답입니다")
    harness = _harness(model, repo)

    result = await harness.run("안녕")

    assert result is not None and result.text().strip() == "응답입니다"
    stored = await repo.get_messages("s1")
    assert [type(m).__name__ for m in stored] == ["UserMessage", "AssistantMessage"]
    assert stored[0].content == "안녕"


@pytest.mark.asyncio
async def test_existing_history_is_loaded_before_the_new_turn(faux_model_with_response, repo):
    await repo.append("s1", UserMessage(content="이전 질문"))
    model = faux_model_with_response("ok")
    spy = SpyMemory()
    harness = _harness(model, repo, spy)

    await harness.run("새 질문")

    # transform은 이전 히스토리 + 이번 user 메시지를 함께 받는다.
    stored = await repo.get_messages("s1")
    assert [getattr(m, "content", None) for m in stored][:3] == ["이전 질문", "새 질문", stored[2].content]


@pytest.mark.asyncio
async def test_no_assistant_message_is_persisted_when_run_is_aborted(
    faux_model_with_response, repo
):
    model = faux_model_with_response("응답")
    harness = _harness(model, repo)

    async def abort_on_start(event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            harness.abort()  # 첫 턴 진입 직전에 중단

    harness.subscribe(abort_on_start)
    result = await harness.run("안녕")

    assert result is None
    # user 메시지는 이미 기록됐지만 assistant 응답은 남지 않는다.
    stored = await repo.get_messages("s1")
    assert [type(m).__name__ for m in stored] == ["UserMessage"]


# ── 작업 기억 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_transform_output_reaches_the_model(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    spy = SpyMemory(prefix="[주입된 컨텍스트]")
    harness = _harness(model, repo, spy)

    await harness.run("안녕")

    assert len(spy.transform_calls) == 1
    # 주입 메시지는 LLM 컨텍스트에만 존재하고 세션 저장소는 오염되지 않는다.
    stored = await repo.get_messages("s1")
    assert all(getattr(m, "content", "") != "[주입된 컨텍스트]" for m in stored)


@pytest.mark.asyncio
async def test_extra_context_flows_into_memory_context(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    spy = SpyMemory()
    harness = _harness(model, repo, spy)

    await harness.run("안녕", extra_context={"user_id": "u1", "roles": ["admin"]})

    ctx = spy.transform_calls[0]
    assert ctx["session_id"] == "s1"
    assert ctx["user_id"] == "u1"
    assert ctx["roles"] == ["admin"]


# ── 이벤트 구독 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_receives_events_and_unsubscribe_stops_them(
    faux_model_with_response, repo
):
    model = faux_model_with_response("ok")
    harness = _harness(model, repo)
    received: list[AgentEvent] = []

    async def sink(event: AgentEvent) -> None:
        received.append(event)

    unsubscribe = harness.subscribe(sink)
    await harness.run("첫 턴")
    first_count = len(received)
    assert first_count > 0
    assert any(isinstance(e, AgentStartEvent) for e in received)

    unsubscribe()
    await harness.run("둘째 턴")
    assert len(received) == first_count


@pytest.mark.asyncio
async def test_listener_exception_does_not_break_the_run(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    harness = _harness(model, repo)
    good: list[AgentEvent] = []

    async def boom(event: AgentEvent) -> None:
        raise RuntimeError("listener down")

    async def good_sink(event: AgentEvent) -> None:
        good.append(event)

    harness.subscribe(boom)
    harness.subscribe(good_sink)

    result = await harness.run("안녕")

    assert result is not None
    assert any(isinstance(e, AgentEndEvent) for e in good)


@pytest.mark.asyncio
async def test_emit_event_reaches_subscribers_outside_the_loop(faux_model, repo):
    harness = _harness(faux_model, repo)
    received: list[AgentEvent] = []

    async def sink(event: AgentEvent) -> None:
        received.append(event)

    harness.subscribe(sink)
    await harness.emit_event(InnerThoughtEvent(session_id="s1", interpretation="생각"))

    assert [type(e).__name__ for e in received] == ["InnerThoughtEvent"]


@pytest.mark.asyncio
async def test_agent_name_is_forwarded_to_loop_events(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    harness = _harness(model, repo, agent_name="researcher")
    received: list[AgentEvent] = []

    async def sink(event: AgentEvent) -> None:
        received.append(event)

    harness.subscribe(sink)
    await harness.run("안녕")

    starts = [e for e in received if isinstance(e, AgentStartEvent)]
    assert starts[0].agent_name == "researcher"


# ── 실행 상태 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_running_toggles_around_the_run(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    harness = _harness(model, repo)
    seen: list[bool] = []

    async def sink(event: AgentEvent) -> None:
        seen.append(harness.is_running)

    harness.subscribe(sink)
    assert harness.is_running is False

    await harness.run("안녕")

    assert all(seen)  # 실행 중 이벤트에서는 항상 True
    assert harness.is_running is False


@pytest.mark.asyncio
async def test_abort_signal_is_cleared_for_the_next_run(faux_model_with_response, repo):
    model = faux_model_with_response("ok")
    harness = _harness(model, repo)
    abort_next = True

    async def abort_on_start(event: AgentEvent) -> None:
        if abort_next and isinstance(event, AgentStartEvent):
            harness.abort()

    harness.subscribe(abort_on_start)
    assert await harness.run("중단될 턴") is None

    # 중단은 그 run에만 적용된다: 다음 run은 signal을 clear하고 정상 수행.
    abort_next = False
    assert await harness.run("정상 턴") is not None


@pytest.mark.asyncio
async def test_abort_before_run_does_not_block_it(faux_model_with_response, repo):
    """run()이 시작 시 signal을 clear하므로, 실행 전 abort는 다음 턴을 막지 않는다."""
    model = faux_model_with_response("ok")
    harness = _harness(model, repo)

    harness.abort()
    assert await harness.run("안녕") is not None


@pytest.mark.asyncio
async def test_tool_executor_is_used_for_tool_calls(faux_model_with_response, repo):
    model = faux_model_with_response(
        "", tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}]
    )
    calls: list[tuple] = []

    async def executor(tool_call_id, tool_name, params):
        calls.append((tool_call_id, tool_name, params))
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="done")]
        )

    harness = _harness(model, repo, loop_config=AgentLoopConfig(max_turns=2))
    await harness.run("파일 읽어", tool_executor=executor)

    assert calls and calls[0][1] == "read_file"
    assert calls[0][2] == {"path": "a"}


@pytest.mark.asyncio
async def test_tool_turn_persists_tool_use_and_tool_result(faux_model_with_response, repo):
    """세션 재개 시 provider 가 tool_use/tool_result 짝을 요구하므로 중간 메시지도 전부 남긴다."""
    model = faux_model_with_response(
        "", tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}]
    )

    async def executor(tool_call_id, tool_name, params):
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="done")]
        )

    harness = _harness(model, repo, loop_config=AgentLoopConfig(max_turns=2))
    await harness.run("파일 읽어", tool_executor=executor)

    stored = await repo.get_messages("s1")
    assert [type(m).__name__ for m in stored] == [
        "UserMessage", "AssistantMessage", "ToolResultMessage", "AssistantMessage", "ToolResultMessage",
    ]
    assert stored[1].tool_calls()[0].id == stored[2].tool_call_id


@pytest.mark.asyncio
async def test_provider_error_persists_only_the_user_message(faux_model, repo):
    from jarvis.model_layer.registry import get_default_registry
    from tests.fixtures.faux_provider import FauxProviderFactory

    get_default_registry()._providers["faux"] = FauxProviderFactory.error()
    harness = _harness(faux_model, repo, SpyMemory())

    result = await harness.run("안녕")

    assert result is not None and result.error_message is not None
    assert [type(m).__name__ for m in await repo.get_messages("s1")] == ["UserMessage"]


async def test_reinforce_gets_called_tools_and_failure(faux_model_with_response, repo):
    """턴 일화의 작업 종류(처음 부른 도구)와 성패는 루프가 쌓은 메시지에서 정한다."""
    model = faux_model_with_response(
        "", tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}]
    )

    async def executor(tool_call_id, tool_name, params):
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="없음")], is_error=True
        )

    memory = SpyMemory()
    await _harness(model, repo, memory, loop_config=AgentLoopConfig(max_turns=2)).run("파일 읽어", executor)
    _, tools, failed = memory.reinforced
    assert tools[0] == "read_file" and failed is True
    assert memory.steps == []  # 실패한 호출은 절차 재료(성공한 단계)에 넣지 않는다


async def test_plain_answer_is_a_successful_turn_without_tools(faux_model_with_response, repo):
    memory = SpyMemory()
    await _harness(faux_model_with_response("안녕하세요"), repo, memory).run("안녕")
    answer, tools, failed = memory.reinforced
    assert answer.strip() == "안녕하세요" and tools == [] and failed is False


async def test_successful_tool_calls_become_steps(faux_model_with_response, repo):
    model = faux_model_with_response("", tool_calls=[{"id": "c1", "name": "read_file", "arguments": {"path": "a"}}])

    async def executor(tool_call_id, tool_name, params):
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="ok")])

    memory = SpyMemory()
    await _harness(model, repo, memory, loop_config=AgentLoopConfig(max_turns=2)).run("파일 읽어", executor)
    assert memory.steps[0] == ("read_file", {"path": "a"})
