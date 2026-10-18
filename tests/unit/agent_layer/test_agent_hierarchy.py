"""[agent_layer] agent_name 이벤트 전파와 계층 추적 단위 테스트."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.ui.tui.bridge import (
    AgentPopAction,
    AgentPushAction,
    EventBridge,
)
from jarvis.agent_layer.types import AgentEndEvent, AgentStartEvent
from jarvis.core.multi_agent.node import AgentNode
from jarvis.core.multi_agent.task import AgentTask

# ── agent_name 이벤트 필드 ─────────────────────────────────────────────────────


def test_agent_start_event_has_agent_name():
    e = AgentStartEvent(session_id="s1", prompt="hi", agent_name="researcher")
    assert e.agent_name == "researcher"


def test_agent_start_event_agent_name_defaults_none():
    e = AgentStartEvent(session_id="s1", prompt="hi")
    assert e.agent_name is None


def test_agent_end_event_has_agent_name():
    e = AgentEndEvent(session_id="s1", agent_name="writer")
    assert e.agent_name == "writer"


def test_agent_end_event_agent_name_defaults_none():
    e = AgentEndEvent(session_id="s1")
    assert e.agent_name is None


# ── EventBridge 계층 번역 ──────────────────────────────────────────────────────


def test_bridge_agent_start_emits_push():
    bridge = EventBridge()
    actions = bridge.translate(AgentStartEvent(session_id="s", prompt="", agent_name="planner"))
    assert len(actions) == 1
    assert isinstance(actions[0], AgentPushAction)
    assert actions[0].agent_name == "planner"


def test_bridge_agent_start_no_name_uses_fallback():
    bridge = EventBridge()
    actions = bridge.translate(AgentStartEvent(session_id="s", prompt=""))
    assert isinstance(actions[0], AgentPushAction)
    assert actions[0].agent_name == "agent"


def test_bridge_agent_end_emits_flush_and_pop():
    bridge = EventBridge()
    actions = bridge.translate(AgentEndEvent(session_id="s", agent_name="planner"))
    kinds = [a.kind for a in actions]
    assert "flush_stream" in kinds
    assert "agent_pop" in kinds


def test_bridge_agent_end_pop_preserves_name():
    bridge = EventBridge()
    actions = bridge.translate(AgentEndEvent(session_id="s", agent_name="executor"))
    pop = next(a for a in actions if isinstance(a, AgentPopAction))
    assert pop.agent_name == "executor"


# ── AgentSession agent_name 프로퍼티 ─────────────────────────────────────────


def test_session_agent_name_settable(permissive_pipeline, agent_session):
    """AgentSession.agent_name 프로퍼티가 읽기/쓰기 모두 동작한다."""
    agent_session.agent_name = "research-agent"
    assert agent_session.agent_name == "research-agent"


def test_session_agent_name_default_none(agent_session):
    assert agent_session.agent_name is None


# ── AgentNode: 세션에 agent_name 주입 ───────────────────────────────────────


def test_node_injects_agent_name_into_session():
    session = MagicMock()
    session.agent_name = None  # 프로퍼티 존재 시뮬레이션
    AgentNode(name="analyst", session=session)
    assert session.agent_name == "analyst"


def test_node_skips_injection_if_session_lacks_attr():
    """session에 agent_name 속성이 없어도 오류 없이 생성된다."""
    session = MagicMock(spec=[])  # 빈 spec: agent_name 없음
    node = AgentNode(name="worker", session=session)
    assert node.name == "worker"


# ── AgentNode: 이벤트 포워딩 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_forwards_events_to_sink():
    """event_sink가 주어지면 서브 에이전트 이벤트가 부모로 전달된다."""
    received: list = []

    async def sink(event):
        received.append(event)

    msg = MagicMock()
    msg.text = "result"
    session = AsyncMock()
    session.prompt.return_value = msg
    session.subscribe = MagicMock(return_value=lambda: None)

    node = AgentNode(name="worker", session=session, event_sink=sink)
    await node.invoke(AgentTask.create("task"))

    session.subscribe.assert_called_once_with(sink)


@pytest.mark.asyncio
async def test_node_unsubscribes_after_invoke():
    """invoke 완료 후 포워딩 구독이 해제된다."""
    unsubscribed = []
    unsub = MagicMock(side_effect=lambda: unsubscribed.append(True))

    msg = MagicMock()
    msg.text = "ok"
    session = AsyncMock()
    session.prompt.return_value = msg
    session.subscribe = MagicMock(return_value=unsub)

    node = AgentNode(name="w", session=session, event_sink=AsyncMock())
    await node.invoke(AgentTask.create("task"))

    assert len(unsubscribed) == 1


@pytest.mark.asyncio
async def test_node_unsubscribes_on_error():
    """invoke 실패 시에도 구독이 해제된다."""
    unsubscribed = []
    unsub = MagicMock(side_effect=lambda: unsubscribed.append(True))

    session = AsyncMock()
    session.prompt.side_effect = RuntimeError("crash")
    session.subscribe = MagicMock(return_value=unsub)

    node = AgentNode(name="w", session=session, event_sink=AsyncMock())
    result = await node.invoke(AgentTask.create("failing task"))

    assert not result.success
    assert len(unsubscribed) == 1


@pytest.mark.asyncio
async def test_node_no_sink_no_subscribe():
    """event_sink가 없으면 session.subscribe를 호출하지 않는다."""
    msg = MagicMock()
    msg.text = "ok"
    session = AsyncMock()
    session.prompt.return_value = msg
    session.subscribe = MagicMock()

    node = AgentNode(name="w", session=session)  # event_sink=None
    await node.invoke(AgentTask.create("task"))

    session.subscribe.assert_not_called()


# ── AgentHarness: agent_name loop에 전달 ────────────────────────────────────


@pytest.mark.asyncio
async def test_harness_passes_agent_name_in_start_event(faux_model_with_response, tmp_path):
    """AgentHarness에 agent_name을 주면 AgentStartEvent에 반영된다."""
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    from jarvis.agent_layer.harness import AgentHarness

    received: list[AgentStartEvent] = []

    async def sink(event):
        if isinstance(event, AgentStartEvent):
            received.append(event)

    model = faux_model_with_response("응답")
    repo = JsonlSessionRepo(sessions_root=str(tmp_path))
    await repo.create(session_id="s1")

    harness = AgentHarness(
        model=model,
        session_id="s1",
        session_repo=repo,
        agent_name="planner",
    )
    harness.subscribe(sink)
    await harness.run("안녕")

    assert len(received) == 1
    assert received[0].agent_name == "planner"


# ── AgentFactory: event_sink 전달 ───────────────────────────────────────────


def test_factory_passes_event_sink_to_node():
    from jarvis.core.multi_agent.factory import AgentDefinition, AgentFactory

    sink = AsyncMock()
    factory = AgentFactory(event_sink=sink)

    session = MagicMock(spec=[])
    defn = AgentDefinition(name="analyst", description="분석가")
    node = factory.create(defn, session)

    assert node._event_sink is sink
