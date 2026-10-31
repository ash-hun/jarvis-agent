"""goal: goals_store 가 같은 목표를 두 번 맡겨도 하나로 두고 다시 열어도 남으며 끝난 목표를 다시 진행하는지 검증."""

from jarvis.core.goals.goals_types import Goal, goal_key
from jarvis.core.goals.goals_store import GoalStore


def make(text: str = "공고만 알려줘") -> Goal:
    return Goal(id=goal_key("karen", text), agent="karen", text=text, created_at=1, updated_at=1)


def test_ensure_twice_keeps_one_goal_and_its_progress(tmp_path):
    store = GoalStore(str(tmp_path))
    first, created = store.ensure(make())
    store.save(first.model_copy(update={"notes": ["진행"]}))
    again, created_again = store.ensure(make())
    assert created and not created_again
    assert again.notes == ["진행"] and len(store.list()) == 1


def test_list_survives_a_new_store_on_the_same_dir(tmp_path):
    GoalStore(str(tmp_path)).ensure(make())
    assert [g.text for g in GoalStore(str(tmp_path)).list("karen")] == ["공고만 알려줘"]
    assert GoalStore(str(tmp_path)).list("main") == []


def test_ensure_reactivates_a_finished_goal(tmp_path):
    store = GoalStore(str(tmp_path))
    goal, _ = store.ensure(make())
    store.save(goal.model_copy(update={"status": "done"}))
    assert store.ensure(make())[0].status == "active"


def test_save_leaves_no_temp_file(tmp_path):
    GoalStore(str(tmp_path)).ensure(make())
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]
