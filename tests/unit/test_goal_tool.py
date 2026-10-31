"""goal: goal 도구가 목표와 작업을 하나씩만 두고 첫 차례를 한 번 돌리며 계속 챙길 말에만 규칙을 붙이는지 검증."""

from jarvis.core.goals.tool import GOAL_RULE, GoalTool, goal_task, standing_rule
from tests.fixtures.goal_helpers import NOW, TEXT, goal_scheduler
from jarvis.core.goals.goals_types import Goal, goal_key
from jarvis.core.tools.tools_registry import ToolContext
from jarvis.core.goals.goals_store import GoalStore
from jarvis.core.scheduler.task import task_label
from jarvis.memory.scope import MemoryScope


async def test_tool_sets_one_goal_and_one_task_and_runs_the_first_turn_once(tmp_path):
    store = GoalStore(str(tmp_path))
    svc = goal_scheduler()
    soon: list[str] = []
    svc.run_soon = lambda task: soon.append(task.name)  # type: ignore[method-assign]
    tool = GoalTool(store, svc, now=lambda: NOW)
    ctx = ToolContext(scope=MemoryScope(user_id="u", agent_id="karen"))
    first = await tool.execute("c", {"action": "set", "text": TEXT}, None, ctx)
    again = await tool.execute("c", {"action": "set", "text": f" {TEXT} "}, None, ctx)
    assert "맡았다" in first.content[0].text and "이미 맡은 목표" in again.content[0].text
    assert len(store.list("karen")) == 1 and len(svc.list_tasks()) == 1 and soon == [svc.list_tasks()[0].name]
    task = svc.list_tasks()[0]
    assert (task.kind, task.agent, task.deliver) == ("goal", "karen", "conversation")
    stopped = await tool.execute("c", {"action": "stop", "text": "원리금"}, None, ctx)
    assert "멈췄다" in stopped.content[0].text and not svc.list_tasks()[0].enabled
    assert store.list("karen")[0].status == "paused"


def test_goal_task_label_shows_its_goal_not_its_id():
    task = goal_task(Goal(id=goal_key("karen", TEXT), agent="karen", text=TEXT))
    assert task_label(task) == f"목표: {TEXT[:60]}"


def test_standing_rule_applies_only_to_standing_requests_of_goal_capable_agents():
    """계속 챙길 일일 수 있는 말에만 목표 규칙을 붙인다. goal 도구가 없는 에이전트에는 붙이지 않는다.
    속생각이 '바로 찾기' 를 선택지로 내면 규칙 없이는 라이브 5번 중 0번 맡았다."""
    tools = {"goal", "housing_budget"}
    standing = (TEXT, "서울에 새 행복주택 공고 나오면 알려줘", "앞으로 추천 1순위 바뀌면 알려줘", "새 공고 계속 챙겨줘")
    for text in standing:
        assert standing_rule(text, tools) == GOAL_RULE, text
    for text in ("현금 1억, 월 150으로 맞는 공고 찾아줘", "가장 추천하는 게 뭐야?"):
        assert standing_rule(text, tools) is None, text
    assert standing_rule(TEXT, {"housing_budget"}) is None
