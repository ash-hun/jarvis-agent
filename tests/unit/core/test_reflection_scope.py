"""[core] 성찰은 자기 세션의 기억 범위(사용자, 에이전트, 세션)를 사고 요청에 실어 보낸다."""

import pytest

from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.core.proactive import DefaultProactivityCore
from jarvis.memory.scope import MemoryScope


class ScopeCapturingEngine:
    """사고 요청에 실린 범위를 기록한다. 회상은 이 범위로 기억을 읽는다."""

    def __init__(self) -> None:
        self.seen: list[MemoryScope] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.seen.append(
            MemoryScope(user_id=request.user_id or "", agent_id=request.agent_id or "", session_id=request.session_id)
        )
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

