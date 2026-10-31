"""multi_agent: AgentNode 의 task_id 캐시와 실패 처리, 자식 세션 이벤트 전달, ResultCache, market 입찰 점수."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.core.multi_agent.node import AgentNode, ResultCache, capability_score
from jarvis.core.multi_agent.task import AgentResult, AgentTask


def make_session(text: str | None = "mock response") -> AsyncMock:
    session = AsyncMock()
    if text is None:
        session.prompt.return_value = None
    else:
        msg = MagicMock()
        msg.text = text
        session.prompt.return_value = msg
    return session


def test_result_cache_returns_stored_result_until_cleared():
    cache = ResultCache()
    result = AgentResult(task_id="t1", agent_name="a", content="ok")

    cache.set("t1", result)

    assert cache.get("t1") is result
    assert cache.get("nonexistent") is None
    cache.clear()
    assert len(cache) == 0


@pytest.mark.parametrize(("text", "content"), [("hello world", "hello world"), (None, "")])
async def test_invoke_returns_session_reply_as_success(text, content):
    node = AgentNode(name="test_agent", session=make_session(text), capabilities=["search"])
    task = AgentTask.create("do something")

    result = await node.invoke(task)

    assert result.success
    assert (result.agent_name, result.content, result.task_id) == ("test_agent", content, task.task_id)


async def test_invoke_turns_session_error_into_failed_result():
    session = AsyncMock()
    session.prompt.side_effect = RuntimeError("LLM unavailable")
    node = AgentNode(name="failing_agent", session=session)

    result = await node.invoke(AgentTask.create("task that fails"))

    assert not result.success
    assert "LLM unavailable" in (result.error or "")
    assert result.content == ""


@pytest.mark.parametrize("fails", [False, True])
async def test_invoke_caches_result_per_task_id(fails):
    session = make_session("first response")
    if fails:
        session.prompt.side_effect = RuntimeError("fail")
    node = AgentNode(name="agent", session=session)
    task = AgentTask.create("same task")

    first = await node.invoke(task)
    session.prompt.return_value.text = "second response"
    again = await node.invoke(task)
    await node.invoke(AgentTask.create("other task"))

    assert again == first
    assert session.prompt.call_count == 2


async def test_clear_cache_allows_retry():
    session = make_session("first")
    node = AgentNode(name="agent", session=session)
    task = AgentTask.create("task")
    await node.invoke(task)

    node.clear_cache()
    session.prompt.return_value.text = "second"
    result = await node.invoke(task)

    assert result.content == "second"
    assert session.prompt.call_count == 2


@pytest.mark.parametrize(
    ("name", "capabilities", "score"),
    [("researcher", ["검색", "논문"], 2.0), ("coder", ["코드"], 0.0), ("검색", [], 1.0)],
)
def test_capability_score_counts_name_and_label_hits(name, capabilities, score):
    task = AgentTask.create("웹 검색 으로 논문 찾기")

    assert capability_score(task, name, capabilities) == score


def _session(prompt_error: Exception | None = None) -> AsyncMock:
    session = AsyncMock()
    if prompt_error is None:
        msg = MagicMock()
        msg.text = "result"
        session.prompt.return_value = msg
    else:
        session.prompt.side_effect = prompt_error
    session.subscribe = MagicMock(return_value=MagicMock())
    return session


def test_node_injects_agent_name_into_session():
    session = MagicMock()
    session.agent_name = None

    AgentNode(name="analyst", session=session)

    assert session.agent_name == "analyst"


def test_node_skips_injection_if_session_lacks_attr():
    session = MagicMock(spec=[])

    node = AgentNode(name="worker", session=session)

    assert node.name == "worker"


async def test_node_forwards_events_to_sink():
    session = _session()

    async def sink(event):
        return None

    await AgentNode(name="worker", session=session, event_sink=sink).invoke(AgentTask.create("task"))

    session.subscribe.assert_called_once_with(sink)


@pytest.mark.parametrize("prompt_error", [None, RuntimeError("crash")], ids=["ok", "error"])
async def test_node_unsubscribes_after_invoke(prompt_error):
    session = _session(prompt_error)

    result = await AgentNode(name="w", session=session, event_sink=AsyncMock()).invoke(AgentTask.create("task"))

    assert result.success is (prompt_error is None)
    session.subscribe.return_value.assert_called_once_with()


async def test_node_without_sink_does_not_subscribe():
    session = _session()

    await AgentNode(name="w", session=session).invoke(AgentTask.create("task"))

    session.subscribe.assert_not_called()
