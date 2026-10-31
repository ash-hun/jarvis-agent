"""multi_agent: AgentTask 의 결정적 task_id 와 AgentTask, AgentResult 의 불변성을 검증한다."""

import pytest

from jarvis.core.multi_agent.task import AgentResult, AgentTask


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        (("research AI trends", None), ("research AI trends", None), True),
        (("task A", None), ("task B", None), False),
        (("task", {"key": "v1"}), ("task", {"key": "v2"}), False),
        (("task", {}), ("task", None), True),
    ],
)
def test_create_task_id_depends_only_on_content_and_context(first, second, same):
    t1 = AgentTask.create(first[0], context=first[1])
    t2 = AgentTask.create(second[0], context=second[1])

    assert (t1.task_id == t2.task_id) is same


def test_create_task_id_is_16_hex_chars():
    task = AgentTask.create("task")

    assert len(task.task_id) == 16
    int(task.task_id, 16)


def test_create_keeps_context_and_parent_task_id():
    ctx = {"user": "ash", "depth": 3}
    parent = AgentTask.create("parent task")

    child = AgentTask.create("child task", context=ctx, parent_task_id=parent.task_id)

    assert child.context == ctx
    assert child.parent_task_id == parent.task_id
    assert parent.parent_task_id is None


@pytest.mark.parametrize(
    "obj",
    [AgentTask.create("task"), AgentResult(task_id="abc", agent_name="agent", content="ok")],
)
def test_task_and_result_are_frozen(obj):
    with pytest.raises((AttributeError, TypeError)):
        obj.content = "modified"


def test_result_defaults_to_success_without_error():
    result = AgentResult(task_id="123", agent_name="a", content="done")

    assert result.success is True
    assert result.error is None
