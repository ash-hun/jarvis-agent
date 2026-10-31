"""goal: /goal 명령이 모델 없이 목표를 맡기고 보여 주고 멈추는지 검증."""

from tests.fixtures.goal_helpers import NOW, TEXT, goal_scheduler
from jarvis.core.slash.goal_cmd import make_goal_handler
from jarvis.core.goals.goals_store import GoalStore
from jarvis.core.goals.tool import GoalTool
from jarvis.memory.scope import MemoryScope


async def test_goal_command_sets_lists_and_stops_without_a_model(tmp_path):
    svc = goal_scheduler()
    svc.run_soon = lambda task: None  # type: ignore[method-assign]
    handle = make_goal_handler(GoalTool(GoalStore(str(tmp_path)), svc, now=lambda: NOW))
    scope = MemoryScope(user_id="u", agent_id="karen")
    assert (await handle(TEXT, scope)).startswith(f"[Goal] 목표를 맡았다: {TEXT}")
    assert "이미 맡은 목표" in await handle(TEXT, scope)
    assert "[active]" in await handle("", scope)
    assert "멈췄다" in await handle("stop 원리금", scope)
    assert "[paused]" in await handle("", scope)
