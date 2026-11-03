"""workflow 의 tracker: 위임 도구 호출과 Focus 바쁨 신호를 간선으로 열고 닫는다."""

from jarvis.agent_layer.agent_types import FocusPanelEvent, ToolExecutionEndEvent, ToolExecutionStartEvent
from jarvis.core.workflow.workflow_tracker import MAX_EDGES, WorkflowTracker, delegation_of


def _start(call_id, tool, args, ts=100):
    return ToolExecutionStartEvent(tool_call_id=call_id, tool_name=tool, args=args, timestamp=ts)


def test_delegation_of_maps_delegation_tools_and_ignores_others():
    assert delegation_of("ask_agent", {"agent": "karen", "message": "m"}) == ("ask", "karen", "m")
    assert delegation_of("agent_researcher", {"task": "t"}) == ("subagent", "researcher", "t")
    orchestrate = delegation_of("orchestrate", {"pattern": "market", "task": "t"})
    assert orchestrate == ("orchestrate", "orchestrate:market", "t")
    assert delegation_of("agent_", {}) is None
    assert delegation_of("bash", {"command": "ls"}) is None


def test_tool_start_and_end_open_then_close_one_edge_idempotently():
    tracker = WorkflowTracker(clock=lambda: 0)
    start = _start("c1", "ask_agent", {"agent": "karen", "message": "뉴스"})
    end = ToolExecutionEndEvent(tool_call_id="c1", tool_name="ask_agent", is_error=True, timestamp=250)

    opened = tracker.observe("s", "main", start)
    assert tracker.observe("s", "main", start) is None
    closed = tracker.observe("s", "main", end)
    assert tracker.observe("s", "main", end) is None

    assert opened is not None and (opened.source, opened.target, opened.started_ms) == ("main", "karen", 100)
    assert closed is not None and (closed.ended_ms, closed.ok) == (250, False)
    assert tracker.edges() == [closed]


def test_focus_busy_reopens_area_edge_at_the_end():
    clock = iter(range(10, 100, 10))
    tracker = WorkflowTracker(clock=lambda: next(clock))
    busy = FocusPanelEvent(session_id="s", area="analysis", markdown="", busy=True)
    idle = FocusPanelEvent(session_id="s", area="analysis", markdown="", busy=False)

    assert tracker.observe("s", "main", idle) is None
    tracker.observe("s", "main", busy)
    tracker.observe("s", "main", idle)
    tracker.observe("s", "main", _start("c1", "agent_x", {"task": "t"}))
    reopened = tracker.observe("s", "main", busy)

    assert [e.target for e in tracker.edges()] == ["x", "focus-analysis"]
    assert reopened is not None and reopened.ended_ms is None


def test_edges_keep_only_the_newest_max_edges():
    tracker = WorkflowTracker(clock=lambda: 0)
    for i in range(MAX_EDGES + 5):
        tracker.observe("s", "main", _start(f"c{i}", "agent_x", {"task": str(i)}))

    edges = tracker.edges()
    assert len(edges) == MAX_EDGES and edges[0].label == "5"
