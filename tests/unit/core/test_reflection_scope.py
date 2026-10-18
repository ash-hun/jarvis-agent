"""[core] 성찰은 자기 세션의 기억 범위로 사고를 기록하고, 끝나면 호출자의 범위를 되돌린다."""

import pytest

from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.memory.scope import MemoryScope, current_scope
from jarvis.core.proactive import DefaultProactivityCore


class ScopeCapturingEngine:
    """think 가 불린 순간의 current_scope 를 기록한다."""

    def __init__(self) -> None:
        self.seen: list[MemoryScope | None] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.seen.append(current_scope.get())
        return ThoughtFrame()


def _session(fx, session_id: str, engine: ScopeCapturingEngine):
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=fx["model"],
        session_id=session_id,
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        proactivity_factory=lambda emit: DefaultProactivityCore(emit_proactive=emit),
    )


@pytest.fixture
def fx(faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo):
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


@pytest.mark.asyncio
async def test_reflection_thinks_in_its_own_session_scope(fx):
    engine = ScopeCapturingEngine()
    first, second = _session(fx, "s1", engine), _session(fx, "s2", engine)

    await first.reflect()
    await second.reflect()

    assert [s.session_id for s in engine.seen] == ["s1", "s2"]
    assert engine.seen[0] == first.memory_scope


@pytest.mark.asyncio
async def test_reflection_restores_callers_scope(fx):
    outer = MemoryScope(user_id="someone", session_id="outer")
    token = current_scope.set(outer)
    try:
        await _session(fx, "s1", ScopeCapturingEngine()).reflect()
        assert current_scope.get() == outer
    finally:
        current_scope.reset(token)
