"""[agent_layer] 병렬 도구 실행에서 도구 하나가 취소돼도 오류 결과로 남고 나머지는 이어진다."""

import pytest
import asyncio

from jarvis.model_layer.types import ToolCall, ToolResultMessage
from jarvis.agent_layer.types import AgentLoopConfig
from jarvis.agent_layer.loop import _execute_tools


async def _noop_emit(_event: object) -> None:
    return None


@pytest.mark.asyncio
async def test_cancelled_tool_becomes_error_result():
    async def executor(call_id: str, name: str, args: dict) -> ToolResultMessage:
        if name == "slow":
            raise asyncio.CancelledError()
        return ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[], is_error=False)

    calls = [ToolCall(id="1", name="slow", arguments={}), ToolCall(id="2", name="fast", arguments={})]
    config = AgentLoopConfig(tool_execution_mode="parallel")
    results = await _execute_tools(calls, executor, config, _noop_emit, None)

    assert [(r.tool_name, r.is_error) for r in results] == [("slow", True), ("fast", False)]
