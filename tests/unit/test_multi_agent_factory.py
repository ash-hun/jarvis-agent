"""multi_agent: memory.stm 정책별 자식 세션 id, 정책 값 검사, 노드 이벤트를 팩토리 sink 로 넘기는지 검증한다."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.multi_agent.factory import AgentDefinition, AgentMemoryPolicy, child_session_id, AgentFactory
from jarvis.core.multi_agent.task import AgentTask
from jarvis.memory import MemoryScope


PARENT = MemoryScope(user_id="jh", agent_id="main", session_id="s1")


TASK = AgentTask.create("t")


@pytest.mark.parametrize(
    ("stm", "expected"),
    [
        ("per_parent_session", "agent_r__s1"),
        ("per_task", f"agent_r__task_{TASK.task_id}"),
        ("per_agent", "agent_r"),
    ],
)
def test_child_session_id_follows_stm_policy(stm, expected):
    definition = AgentDefinition(name="r", description="d", memory=AgentMemoryPolicy(stm=stm))

    assert child_session_id(definition, PARENT, TASK) == expected


def test_memory_policy_rejects_unknown_stm():
    with pytest.raises(ValueError):
        AgentMemoryPolicy(stm="forever")  # type: ignore[arg-type]


async def test_factory_passes_event_sink_to_node():
    sink = AsyncMock()
    session = AsyncMock()
    session.prompt.return_value = MagicMock(text="ok")
    session.subscribe = MagicMock(return_value=lambda: None)
    node = AgentFactory(event_sink=sink).create(AgentDefinition(name="analyst", description="분석가"), session)

    await node.invoke(AgentTask.create("task"))

    session.subscribe.assert_called_once_with(sink)
