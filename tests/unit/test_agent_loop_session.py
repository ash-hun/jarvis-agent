"""agent_loop: AgentSession.prompt 의 한 턴 흐름, 입력 검증, 영속, 동시 요청 거절과 세션 해제를 검증한다."""

import pytest
import asyncio
from unittest.mock import AsyncMock
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import (
    LLMContext,
    ModelConfig,
    StreamEvent,
    StreamOptions,
    TextContent,
    ToolResultMessage,
)
from tests.fixtures.agent_loop_helpers import ScriptedProvider, register, text_turn
from jarvis.core.session import AgentSession, SessionBusy
from jarvis.core.policy.pipeline import ValidationError
from jarvis.agent_layer.agent_types import AgentEvent
from jarvis.core.skills.skills_registry import Skill
import jarvis.core.session as session_module


class GatedProvider(ScriptedProvider):
    """gate 가 열릴 때까지 응답을 붙잡아 턴이 도는 중인 세션을 만든다."""

    def __init__(self) -> None:
        super().__init__([text_turn("ok")])
        self.gate = asyncio.Event()

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        await self.gate.wait()
        async for event in super().stream(model, context, options):
            yield event


@pytest.fixture
async def make_session(permissive_pipeline, plugin_runner, tool_registry, skill_registry, jsonl_repo):
    await jsonl_repo.create(session_id="gated")

    def _make(model: ModelConfig) -> AgentSession:
        return AgentSession(
            model=model,
            session_id="gated",
            security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            session_repo=jsonl_repo,
        )

    return _make


async def test_prompt_returns_model_reply(agent_session, faux_model_with_response):
    faux_model_with_response("Hello from Jarvis!")

    result = await agent_session.prompt("Hello!")

    assert result is not None
    assert "Hello" in result.text()


@pytest.mark.parametrize("raw", ["", "<script>alert(1)</script>"])
async def test_prompt_rejects_invalid_input(agent_session, raw):
    with pytest.raises(ValidationError):
        await agent_session.prompt(raw)


async def test_prompt_emits_start_and_end_events(agent_session, faux_model_with_response):
    faux_model_with_response("Test response")
    captured: list[AgentEvent] = []

    async def listener(event: AgentEvent):
        captured.append(event)

    agent_session.subscribe(listener)

    await agent_session.prompt("Hello!")

    event_types = [type(e).__name__ for e in captured]
    assert "AgentStartEvent" in event_types
    assert "AgentEndEvent" in event_types


async def test_prompt_expands_skill_command(agent_session, skill_registry, faux_model_with_response):
    faux_model_with_response("Summarized!")
    skill_registry.register(
        Skill(name="sum", description="Summarize", aliases=[], content="Please summarize: {{args}}", metadata={})
    )

    result = await agent_session.prompt("/sum some long text")

    assert result is not None


async def test_prompt_runs_registered_tool(agent_session, tool_registry, faux_model_with_response):
    call_log = []

    class TestTool:
        name = "test-tool"
        description = "Test"
        parameters = {"type": "object", "properties": {}}
        execution_mode = "parallel"

        async def execute(self, tool_call_id, params, signal=None):
            call_log.append(params)
            return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text="done")])

    tool_registry.register(TestTool())
    faux_model_with_response(response="", tool_calls=[{"id": "tc_01", "name": "test-tool", "arguments": {"x": 1}}])

    result = await agent_session.prompt("Use the test tool")

    assert result is not None


async def test_abort_during_prompt_finishes_without_error(agent_session, faux_model_with_response):
    faux_model_with_response("This is a long response with many words to stream")

    task = asyncio.create_task(agent_session.prompt("Hello"))
    await asyncio.sleep(0.01)
    agent_session.abort()

    await task


@pytest.mark.parametrize("turns", [1, 2])
async def test_prompt_persists_user_and_assistant_per_turn(agent_session, faux_model_with_response, jsonl_repo, turns):
    for i in range(turns):
        faux_model_with_response(f"Turn {i} response")
        assert await agent_session.prompt(f"Turn {i}") is not None

    messages = await jsonl_repo.get_messages("test-session")

    assert len(messages) >= 2 * turns


def test_agent_name_defaults_none_and_is_settable(agent_session):
    assert agent_session.agent_name is None

    agent_session.agent_name = "research-agent"

    assert agent_session.agent_name == "research-agent"


async def test_second_prompt_is_rejected_while_first_runs(make_session, monkeypatch):
    # 긴 작업 도중에 온 요청은 잠깐 기다린 뒤에도 거절한다. 테스트에서는 기다림을 짧게
    monkeypatch.setattr(session_module, "BUSY_GRACE_SEC", 0.05)
    provider = GatedProvider()
    session = make_session(register(provider))
    first = asyncio.create_task(session.prompt("첫 요청"))
    await asyncio.sleep(0)

    assert session.is_running is True
    with pytest.raises(SessionBusy):
        await session.prompt("두 번째 요청")

    provider.gate.set()
    await first
    assert session.is_running is False
    await session.prompt("세 번째 요청")


async def test_prompt_sent_during_the_wrap_up_waits_instead_of_failing(make_session):
    provider = GatedProvider()
    session = make_session(register(provider))
    first = asyncio.create_task(session.prompt("첫 요청"))
    await asyncio.sleep(0)
    second = asyncio.create_task(session.prompt("바로 이어 보낸 요청"))
    await asyncio.sleep(0.05)

    provider.gate.set()
    await first
    await second

    assert len(provider.calls) == 2


async def test_failure_before_main_loop_releases_the_session(agent_session, faux_model_with_response):
    faux_model_with_response("ok")
    with pytest.raises(ValidationError):
        await agent_session.prompt("")

    assert agent_session.is_running is False
    assert (await agent_session.prompt("정상 요청")) is not None


async def test_main_loop_exception_releases_the_session(agent_session):
    # harness.run 을 바꿔 끼운다. 실제 프로바이더 예외는 harness 의 실행 표시를 남겨 세션 해제만 따로 볼 수 없다
    agent_session._harness.run = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await agent_session.prompt("터질 요청")

    assert agent_session.is_running is False
