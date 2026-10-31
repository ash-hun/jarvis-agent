"""multi_agent: AgentNodeTool 이 노드 결과를 도구 결과로 바꾸고 이름과 실행 모드를 정하는지 검증한다."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.multi_agent.tool import AgentNodeTool
from jarvis.core.multi_agent.node import AgentNode


@pytest.mark.parametrize("fails", [False, True])
async def test_execute_reports_node_result(fails):
    session = AsyncMock()
    if fails:
        session.prompt.side_effect = RuntimeError("crash")
    else:
        session.prompt.return_value = MagicMock(text="tool result")
    tool = AgentNodeTool(AgentNode(name="worker", session=session, capabilities=["write"]))

    result = await tool.execute("call_1", {"task": "write a summary"})

    assert result.is_error is fails
    assert ("crash" if fails else "tool result") in result.content[0].text


def test_tool_is_named_after_node_and_runs_sequentially():
    tool = AgentNodeTool(AgentNode(name="researcher", session=AsyncMock()))

    assert tool.name == "agent_researcher"
    assert tool.execution_mode == "sequential"
