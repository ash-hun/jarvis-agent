"""AgentSession 턴 훅: 시스템 프롬프트에 Focus 맥락을 더하고, 턴 앞뒤로 훅을 부른다."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from jarvis.model_layer.registry import get_default_registry
from jarvis.model_layer.types import LLMContext, ModelConfig, StreamEvent, StreamOptions
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


class _Hook:
    def __init__(self) -> None:
        self.before: list[str] = []
        self.after: list[tuple[str, str]] = []

    def system_addendum(self) -> str | None:
        return "[Focus 모드] 작업: 발표 자료"

    async def before_turn(self, user_input: str) -> None:
        self.before.append(user_input)

    async def after_turn(self, user_input: str, reply: str) -> None:
        self.after.append((user_input, reply))


def _session(fx: dict[str, Any]) -> Any:
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=ModelConfig(provider="faux", model="faux-model"),
        session_id="focus-hook",
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory_chain=fx["memory_chain"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
    )


async def test_hook_adds_context_and_runs_around_turn(
    monkeypatch, permissive_pipeline, plugin_runner, memory_chain, tool_registry, skill_registry, jsonl_repo
) -> None:
    provider = _Recording()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    fx = {
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "memory_chain": memory_chain,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }
    await jsonl_repo.create(session_id="focus-hook")
    session, hook = _session(fx), _Hook()
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
