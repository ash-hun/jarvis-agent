"""core/session.py — AgentSession 전체 흐름 테스트 (faux provider 사용)."""
import pytest

from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.agent_layer.agent_types import (
    AgentEvent,
)
from jarvis.core.policy.pipeline import ValidationError


class TestAgentSessionPrompt:
    async def test_basic_prompt_returns_message(self, agent_session, faux_model_with_response):
        faux_model_with_response("Hello from Jarvis!")
        result = await agent_session.prompt("Hello!")
        assert result is not None
        assert "Hello" in result.text()

    async def test_empty_input_raises_validation_error(self, agent_session):
        with pytest.raises(ValidationError):
            await agent_session.prompt("")

    async def test_xss_input_blocked(self, agent_session):
        with pytest.raises(ValidationError):
            await agent_session.prompt("<script>alert(1)</script>")

    async def test_events_emitted_in_order(self, agent_session, faux_model_with_response):
        faux_model_with_response("Test response")
        events: list[AgentEvent] = []

        agent_session.subscribe(lambda e: events.append(e) or __import__("asyncio").sleep(0))

        # subscribe는 async listener를 기대하므로 재정의
        captured = []

        async def listener(event: AgentEvent):
            captured.append(event)

        agent_session.subscribe(listener)
        await agent_session.prompt("Hello!")

        event_types = [type(e).__name__ for e in captured]
        assert "AgentStartEvent" in event_types
        assert "AgentEndEvent" in event_types

    async def test_skill_expansion(self, agent_session, faux_model_with_response):
        from jarvis.core.skills.skills_registry import Skill

        faux_model_with_response("Summarized!")
        agent_session._skill_registry.register(Skill(
            name="sum",
            description="Summarize",
            aliases=[],
            content="Please summarize: {{args}}",
            metadata={},
        ))

        result = await agent_session.prompt("/sum some long text")
        assert result is not None

    async def test_tool_execution_with_policy(self, agent_session, faux_model_with_response):

        call_log = []

        class TestTool:
            name = "test-tool"
            description = "Test"
            parameters = {"type": "object", "properties": {}}
            execution_mode = "parallel"

            async def execute(self, tool_call_id, params, signal=None):
                call_log.append(params)
                return ToolResultMessage(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    content=[TextContent(text="done")],
                )

        agent_session._tool_registry.register(TestTool())
        faux_model_with_response(
            response="",
            tool_calls=[{"id": "tc_01", "name": "test-tool", "arguments": {"x": 1}}],
        )

        result = await agent_session.prompt("Use the test tool")
        assert result is not None

    async def test_abort_stops_execution(self, agent_session, faux_model_with_response):
        import asyncio

        faux_model_with_response("This is a long response with many words to stream")

        async def prompt_and_abort():
            task = asyncio.create_task(agent_session.prompt("Hello"))
            await asyncio.sleep(0.01)
            agent_session.abort()
            return await task

        await prompt_and_abort()


class TestAgentSessionSession:
    async def test_session_persists_messages(self, agent_session, faux_model_with_response, jsonl_repo):
        faux_model_with_response("Response 1")
        await agent_session.prompt("Question 1")

        messages = await jsonl_repo.get_messages("test-session")
        assert len(messages) >= 2  # user + assistant

    async def test_multiple_turns(self, agent_session, faux_model_with_response):
        faux_model_with_response("Turn 1 response")
        r1 = await agent_session.prompt("Turn 1")
        assert r1 is not None

        faux_model_with_response("Turn 2 response")
        r2 = await agent_session.prompt("Turn 2")
        assert r2 is not None

        messages = await agent_session._harness._session_repo.get_messages("test-session")
        assert len(messages) >= 4


# ── 동시 프롬프트 거부 ─────────────────────────────────────────────────────────


class TestConcurrentPromptIsRejected:
    async def test_second_prompt_is_rejected_while_first_runs(
        self, agent_session, faux_model_with_response, monkeypatch
    ):
        import asyncio
        from unittest.mock import AsyncMock

        import jarvis.core.session as session_module
        from jarvis.core.session import SessionBusy

        # 긴 작업 도중에 온 요청은 잠깐 기다린 뒤에도 거절한다. 테스트에서는 기다림을 짧게
        monkeypatch.setattr(session_module, "BUSY_GRACE_SEC", 0.05)
        faux_model_with_response("ok")
        gate = asyncio.Event()

        async def slow_run(**_kw):
            await gate.wait()
            return None

        agent_session._harness.run = AsyncMock(side_effect=slow_run)
        first = asyncio.create_task(agent_session.prompt("첫 요청"))
        await asyncio.sleep(0)

        assert agent_session.is_running is True
        with pytest.raises(SessionBusy):
            await agent_session.prompt("두 번째 요청")

        gate.set()
        await first
        assert agent_session.is_running is False
        # 첫 요청이 끝나면 다시 받는다.
        await agent_session.prompt("세 번째 요청")

    async def test_prompt_sent_during_the_wrap_up_waits_instead_of_failing(
        self, agent_session, faux_model_with_response
    ):
        import asyncio
        from unittest.mock import AsyncMock

        faux_model_with_response("ok")
        gate = asyncio.Event()

        async def wrapping_up(**_kw):
            # 화면은 agent_end 를 이미 받았고 세션은 대화를 저장하는 중이다
            await gate.wait()
            return None

        agent_session._harness.run = AsyncMock(side_effect=wrapping_up)
        first = asyncio.create_task(agent_session.prompt("첫 요청"))
        await asyncio.sleep(0)
        second = asyncio.create_task(agent_session.prompt("바로 이어 보낸 요청"))
        await asyncio.sleep(0.05)
        gate.set()
        await first
        await second  # 거절되지 않고 첫 요청이 끝난 뒤 처리된다
        assert agent_session._harness.run.await_count == 2

    async def test_failure_before_main_loop_releases_the_session(self, agent_session, faux_model_with_response):
        faux_model_with_response("ok")
        with pytest.raises(ValidationError):
            await agent_session.prompt("")
        assert agent_session.is_running is False
        assert (await agent_session.prompt("정상 요청")) is not None

    async def test_main_loop_exception_releases_the_session(self, agent_session, faux_model_with_response):
        from unittest.mock import AsyncMock

        faux_model_with_response("ok")
        agent_session._harness.run = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await agent_session.prompt("터질 요청")
        assert agent_session.is_running is False
