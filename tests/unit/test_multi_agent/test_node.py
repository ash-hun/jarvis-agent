"""AgentNode / AgentNodeTool 단위 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.core.multi_agent.node import AgentNode, ResultCache
from jarvis.core.multi_agent.task import AgentTask

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def make_session(text: str = "mock response") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    session = AsyncMock()
    session.prompt.return_value = msg
    return session


# ── ResultCache ────────────────────────────────────────────────────────────────


def test_cache_miss_returns_none():
    cache = ResultCache()
    assert cache.get("nonexistent") is None


def test_cache_set_and_get():
    from jarvis.core.multi_agent.task import AgentResult

    cache = ResultCache()
    r = AgentResult(task_id="t1", agent_name="a", content="ok")
    cache.set("t1", r)
    assert cache.get("t1") is r


def test_cache_clear():
    from jarvis.core.multi_agent.task import AgentResult

    cache = ResultCache()
    cache.set("t1", AgentResult(task_id="t1", agent_name="a", content="ok"))
    cache.clear()
    assert len(cache) == 0


# ── AgentNode ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_invoke_success():
    session = make_session("hello world")
    node = AgentNode(name="test_agent", session=session, capabilities=["search"])
    task = AgentTask.create("do something")

    result = await node.invoke(task)

    assert result.success
    assert result.agent_name == "test_agent"
    assert result.content == "hello world"
    assert result.task_id == task.task_id


@pytest.mark.asyncio
async def test_node_invoke_idempotent():
    """동일 task_id 재호출 → 캐시 반환, 세션 1회만 호출."""
    session = make_session("first response")
    node = AgentNode(name="idempotent_agent", session=session)
    task = AgentTask.create("same task")

    result1 = await node.invoke(task)

    # 응답 교체 후 동일 task로 재호출
    session.prompt.return_value.text = "second response"
    result2 = await node.invoke(task)

    assert result1.content == result2.content == "first response"
    assert session.prompt.call_count == 1


@pytest.mark.asyncio
async def test_node_invoke_different_tasks_call_session_twice():
    session = make_session("response")
    node = AgentNode(name="agent", session=session)

    task_a = AgentTask.create("task A")
    task_b = AgentTask.create("task B")

    await node.invoke(task_a)
    await node.invoke(task_b)

    assert session.prompt.call_count == 2


@pytest.mark.asyncio
async def test_node_invoke_error_handling():
    session = AsyncMock()
    session.prompt.side_effect = RuntimeError("LLM unavailable")
    node = AgentNode(name="failing_agent", session=session)

    result = await node.invoke(AgentTask.create("task that fails"))

    assert not result.success
    assert "LLM unavailable" in (result.error or "")
    assert result.content == ""


@pytest.mark.asyncio
async def test_node_invoke_error_is_cached():
    """실패 결과도 캐싱 — 재시도는 clear_cache() 후 명시적으로."""
    session = AsyncMock()
    session.prompt.side_effect = RuntimeError("fail")
    node = AgentNode(name="agent", session=session)
    task = AgentTask.create("bad task")

    await node.invoke(task)
    await node.invoke(task)  # 동일 task

    assert session.prompt.call_count == 1  # 두 번째는 캐시


@pytest.mark.asyncio
async def test_node_clear_cache_allows_retry():
    session = make_session("first")
    node = AgentNode(name="agent", session=session)
    task = AgentTask.create("task")

    await node.invoke(task)
    node.clear_cache()

    session.prompt.return_value.text = "second"
    result = await node.invoke(task)

    assert result.content == "second"
    assert session.prompt.call_count == 2


@pytest.mark.asyncio
async def test_node_can_handle_default_true():
    node = AgentNode(name="agent", session=AsyncMock())
    assert await node.can_handle(AgentTask.create("any task")) is True


@pytest.mark.asyncio
async def test_node_session_none_response():
    """session.prompt()가 None을 반환해도 성공 처리 (content 빈 문자열)."""
    session = AsyncMock()
    session.prompt.return_value = None
    node = AgentNode(name="agent", session=session)

    result = await node.invoke(AgentTask.create("task"))

    assert result.success
    assert result.content == ""


# ── AgentNodeTool ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_node_tool_execute_success():
    from jarvis.core.multi_agent.tool import AgentNodeTool

    session = make_session("tool result")
    node = AgentNode(name="worker", session=session, capabilities=["write"])
    tool = AgentNodeTool(node)

    result = await tool.execute("call_1", {"task": "write a summary"})

    assert not result.is_error
    assert "tool result" in result.content[0].text


@pytest.mark.asyncio
async def test_agent_node_tool_execute_error():
    from jarvis.core.multi_agent.tool import AgentNodeTool

    session = AsyncMock()
    session.prompt.side_effect = RuntimeError("crash")
    node = AgentNode(name="broken", session=session)
    tool = AgentNodeTool(node)

    result = await tool.execute("call_2", {"task": "something"})

    assert result.is_error


def test_agent_node_tool_name_prefix():
    from jarvis.core.multi_agent.tool import AgentNodeTool

    node = AgentNode(name="researcher", session=AsyncMock())
    tool = AgentNodeTool(node)
    assert tool.name == "agent_researcher"


def test_agent_node_tool_execution_mode():
    from jarvis.core.multi_agent.tool import AgentNodeTool

    node = AgentNode(name="x", session=AsyncMock())
    tool = AgentNodeTool(node)
    assert tool.execution_mode == "sequential"
