"""focus 기능: 세션 턴 훅이 시스템 프롬프트에 맥락을 더하고 턴 앞뒤로 불리며, 그동안 먼저 거는 말을 막는다."""

import pytest
import asyncio
from typing import Any
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamEvent, StreamOptions
from jarvis.core.proactive.proactive_types import ProactiveMessage
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.core.session import AgentSession, TurnHook
from tests.fixtures.faux_provider import FauxProvider


class _Recording(FauxProvider):
    def __init__(self) -> None:
        super().__init__(response="목차를 정리했습니다")
        self.system_prompts: list[str | None] = []

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.system_prompts.append(context.system_prompt)
        async for event in super().stream(model, context, options):
            yield event


class _Hook(TurnHook):
    def __init__(self) -> None:
        self.before: list[str] = []
        self.after: list[tuple[str, str]] = []

    def system_addendum(self) -> str | None:
        return "[Focus 모드] 작업: 발표 자료"

    async def before_turn(self, user_input: str) -> None:
        self.before.append(user_input)

    async def after_turn(self, user_input: str, reply: str) -> None:
        self.after.append((user_input, reply))


@pytest.fixture
def session(
    permissive_pipeline: Any,
    plugin_runner: Any,
    session_memory: Any,
    tool_registry: Any,
    skill_registry: Any,
    jsonl_repo: Any,
) -> AgentSession:
    return AgentSession(
        model=ModelConfig(provider="faux", model="faux-model"),
        session_id="focus-hook",
        security_pipeline=permissive_pipeline,
        plugin_runner=plugin_runner,
        memory=session_memory,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        session_repo=jsonl_repo,
    )


async def test_hook_adds_context_and_runs_around_turn(
    monkeypatch: pytest.MonkeyPatch, session: AgentSession, jsonl_repo: Any
) -> None:
    provider = _Recording()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    await jsonl_repo.create(session_id="focus-hook")
    hook = _Hook()
    session.set_turn_hook(hook)

    await session.prompt("목차를 짜 줘")
    for _ in range(5):
        await asyncio.sleep(0)

    assert "[Focus 모드] 작업: 발표 자료" in (provider.system_prompts[-1] or "")
    assert hook.before == ["목차를 짜 줘"]
    assert hook.after == [("목차를 짜 줘", "목차를 정리했습니다 ")]

    session.set_turn_hook(None)
    await session.prompt("고마워")

    assert "[Focus 모드]" not in (provider.system_prompts[-1] or "")
    assert hook.before == ["목차를 짜 줘"]


@pytest.mark.parametrize("gate", ["turn_hook", "busy"])
async def test_proactive_push_is_quiet_while_gated_but_filler_passes(session: AgentSession, gate: str) -> None:
    seen: list[tuple[str, str]] = []

    async def listen(event: Any) -> None:
        if event.type == "proactive_message":
            seen.append((event.kind, event.text))

    def close_gate(closed: bool) -> None:
        if gate == "turn_hook":
            session.set_turn_hook(_Hook() if closed else None)
        else:
            session._set_busy(closed)

    session.subscribe(listen)

    close_gate(True)
    await session._emit_proactive(ProactiveMessage(text="조건을 말씀해 주세요", kind="proactive"))
    await session._emit_proactive(ProactiveMessage(text="잠깐만요", kind="filler"))
    close_gate(False)
    await session._emit_proactive(ProactiveMessage(text="공고 마감이 내일이에요", kind="proactive"))

    assert seen == [("filler", "잠깐만요"), ("proactive", "공고 마감이 내일이에요")]


async def test_base_turn_hook_adds_nothing_and_does_nothing() -> None:
    hook = TurnHook()

    await hook.before_turn("x")
    await hook.after_turn("x", "y")

    assert hook.system_addendum() is None
