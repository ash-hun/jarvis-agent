"""AgentTask / AgentResult 단위 테스트 — 멱등성 검증 중심."""

import pytest

from jarvis.core.multi_agent.task import AgentResult, AgentTask


# ── AgentTask ──────────────────────────────────────────────────────────────────


def test_task_create_deterministic():
    """동일 입력 → 동일 task_id (멱등성 핵심)."""
    t1 = AgentTask.create("research AI trends")
    t2 = AgentTask.create("research AI trends")
    assert t1.task_id == t2.task_id


def test_task_different_content_different_id():
    t1 = AgentTask.create("task A")
    t2 = AgentTask.create("task B")
    assert t1.task_id != t2.task_id


def test_task_context_affects_id():
    t1 = AgentTask.create("task", context={"key": "v1"})
    t2 = AgentTask.create("task", context={"key": "v2"})
    assert t1.task_id != t2.task_id


def test_task_empty_context_same_as_none():
    t1 = AgentTask.create("task", context={})
    t2 = AgentTask.create("task", context=None)
    assert t1.task_id == t2.task_id


def test_task_is_frozen():
    t = AgentTask.create("task")
    with pytest.raises((AttributeError, TypeError)):
        t.content = "modified"  # type: ignore[misc]


def test_task_parent_id_propagation():
    parent = AgentTask.create("parent task")
    child = AgentTask.create("child task", parent_task_id=parent.task_id)
    assert child.parent_task_id == parent.task_id


def test_task_no_parent_by_default():
    t = AgentTask.create("standalone")
    assert t.parent_task_id is None


def test_task_id_is_hex_string():
    t = AgentTask.create("task")
    assert len(t.task_id) == 16
    int(t.task_id, 16)  # 16진수 검증 — 예외 없으면 OK


def test_task_context_dict_preserved():
    ctx = {"user": "ash", "depth": 3}
    t = AgentTask.create("task", context=ctx)
    assert t.context == ctx


# ── AgentResult ────────────────────────────────────────────────────────────────


def test_result_frozen():
    r = AgentResult(task_id="abc", agent_name="agent", content="ok")
    with pytest.raises((AttributeError, TypeError)):
        r.content = "modified"  # type: ignore[misc]


def test_result_default_success_true():
    r = AgentResult(task_id="123", agent_name="a", content="done")
    assert r.success is True
    assert r.error is None


def test_result_failure():
    r = AgentResult(task_id="123", agent_name="a", content="", success=False, error="timeout")
    assert not r.success
    assert r.error == "timeout"


def test_result_task_id_matches_task():
    task = AgentTask.create("my task")
    result = AgentResult(task_id=task.task_id, agent_name="agent", content="done")
    assert result.task_id == task.task_id
