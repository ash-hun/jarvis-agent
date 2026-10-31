"""AgentSession 턴 훅: 시스템 프롬프트에 Focus 맥락을 더하고, 턴 앞뒤로 훅을 부른다."""

import asyncio
from typing import Any
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamEvent, StreamOptions
from jarvis.model_layer.model_registry import get_default_registry
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
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
    )


async def test_hook_adds_context_and_runs_around_turn(
    monkeypatch, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    provider = _Recording()
    monkeypatch.setitem(get_default_registry()._providers, "faux", provider)
    fx = {
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
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


async def test_proactive_push_is_quiet_while_hook_is_set(
    permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
) -> None:
    from jarvis.core.proactive.proactive_types import ProactiveMessage

    fx = {
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }
    session = _session(fx)
    seen: list[tuple[str, str]] = []

    async def listen(event: Any) -> None:
        if event.type == "proactive_message":
            seen.append((event.kind, event.text))

    session._harness.subscribe(listen)
    session.set_turn_hook(_Hook())
    await session._emit_proactive(ProactiveMessage(text="물 마실 시간이에요", kind="proactive"))
    await session._emit_proactive(ProactiveMessage(text="잠깐만요", kind="filler"))
    session.set_turn_hook(None)
    await session._emit_proactive(ProactiveMessage(text="물 마실 시간이에요", kind="proactive"))

    assert seen == [("filler", "잠깐만요"), ("proactive", "물 마실 시간이에요")]


async def test_no_proactive_message_while_the_agent_is_answering(
    permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
):
    from jarvis.core.proactive.proactive_types import ProactiveMessage

    fx = {
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }
    session = _session(fx)
    seen: list[tuple[str, str]] = []

    async def listen(event: Any) -> None:
        if event.type == "proactive_message":
            seen.append((event.kind, event.text))

    session._harness.subscribe(listen)
    session._set_busy(True)
    await session._emit_proactive(ProactiveMessage(text="조건을 말씀해 주세요", kind="proactive"))
    await session._emit_proactive(ProactiveMessage(text="잠깐만요", kind="filler"))
    session._set_busy(False)
    await session._emit_proactive(ProactiveMessage(text="공고 마감이 내일이에요", kind="proactive"))

    # 답하는 중에는 🔔 를 내지 않고, filler 와 답이 끝난 뒤의 🔔 는 낸다
    assert seen == [("filler", "잠깐만요"), ("proactive", "공고 마감이 내일이에요")]
