"""agent_loop: 하네스, 루프, 기억을 이어 max_turns 를 넘긴 턴이 이어가서 답하고 턴 일화에 overflow 를 남기는지 본다."""

import pytest

from tests.fixtures.agent_loop_helpers import ScriptedProvider, register, text_turn, tool_turn
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.memory.memory_service import TURN_SOURCE, MemoryService
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.agent_types import AgentLoopConfig
from jarvis.agent_layer.harness import AgentHarness
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local", agent_id="main", session_id="s1")


async def _executor(tool_call_id: str, tool_name: str, params: dict) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=tool_call_id, tool_name=tool_name, content=[TextContent(text="42")])


@pytest.mark.parametrize(("max_turns", "overflow"), [(2, True), (5, None)], ids=["overflowed", "within_budget"])
async def test_turn_episode_marks_overflow_only_when_loop_resumed(jsonl_repo, max_turns, overflow):
    await jsonl_repo.create(session_id="s1")
    memory = MemoryService(InMemoryItemStore())
    provider = ScriptedProvider(
        [tool_turn(("c1", "read_file", {"path": "a"})), tool_turn(("c2", "bash", {"command": "ls"})),
         text_turn("한 것: 42 를 읽음\n남은 단계: 답하기"), text_turn("답은 42")]
    )
    harness = AgentHarness(
        model=register(provider), session_id="s1", session_repo=jsonl_repo, memory=memory,
        loop_config=AgentLoopConfig(max_turns=max_turns),
    )

    result = await harness.run("값을 찾아줘", _executor)

    assert result is not None and result.text() in {"답은 42", "한 것: 42 를 읽음\n남은 단계: 답하기"}
    [item] = [i for i in await memory.store.recent(SCOPE, limit=10) if i.source == TURN_SOURCE]
    assert item.metadata.get("overflow") is overflow
    history = await jsonl_repo.get_messages("s1")
    assert all("남은 단계" not in str(getattr(m, "content", "")) for m in history[:-1])
