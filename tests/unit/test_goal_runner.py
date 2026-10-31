"""goal: runner 의 한 차례가 프롬프트를 짓고 경계 밖 도구를 빼며 이미 알린 것과 꼴이 아닌 답을 막는지 검증."""

import pytest
from typing import Any

from tests.fixtures.goal_helpers import HEAD, NOW, REPLY, SAID, TEXT, Final, goal_setup, registry
from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.goals.runner import build_prompt, step_registry
from jarvis.core.goals.goals_types import Goal
from jarvis.memory.scope import MemoryScope


def replying(*replies: str | None):  # type: ignore[no-untyped-def]
    queue = list(replies)
    seen: list[tuple[str, ToolRegistry]] = []

    async def run(prompt, pick):  # type: ignore[no-untyped-def]
        tools = pick(registry("housing_budget", "housing_profile"))
        seen.append((prompt, tools))
        if tools.get("housing_budget") is not None:
            await tools.execute("c", "housing_budget", {}, None, None)
        return queue.pop(0)

    return run, seen


def test_build_prompt_shows_goal_progress_and_boundary_but_not_what_was_reported():
    goal = Goal(id="g", agent="karen", text=TEXT, notes=["첫 확인"], reported=["2026:55A"])
    prompt = build_prompt(goal, ["housing_budget"], ["housing_profile"], NOW)
    assert TEXT in prompt and "2026-10-28 10:00" in prompt and "- 첫 확인" in prompt
    # 알렸는지는 코드가 가린다. 모델이 이 목록을 보고 새 것까지 빼거나 엉뚱한 것을 물었다
    assert "2026:55A" not in prompt
    assert "혼자 해도 되는 도구: housing_budget" in prompt and "먼저 물어야 하는 일: housing_profile" in prompt


async def test_step_registry_drops_ask_tools_and_never_ends_the_turn_with_raw_results():
    tools = step_registry(registry("housing_budget", "housing_profile"), ("housing_profile",))
    assert [t.name for t in tools.list_all()] == ["housing_budget"]
    result = await tools.execute("c", "housing_budget", {}, None, ToolContext(scope=MemoryScope(user_id="u")))
    assert result.final is False and result.content[0].text == "결과"


@pytest.mark.parametrize(
    ("goal_turn", "expected"),
    [(True, {"regions": "서울"}), (False, {"cash": "1억", "regions": "서울"})],
    ids=["goal_turn_drops", "scheduled_task_keeps"],
)
async def test_step_registry_drops_user_only_values_only_in_goal_turns(goal_turn, expected):
    """사람이 없는 목표 차례에서는 모델이 현금 같은 값을 지어내도 버리고 저장된 값으로 돈다(실측: 18번 중 1번 지어냄).
    사용자가 적어 둔 스케줄 작업은 그 값을 그대로 쓴다."""
    seen: list[dict[str, Any]] = []

    class Budget(Final):
        user_only_params = ("cash",)

        async def execute(self, tool_call_id, params, signal=None, context=None):  # type: ignore[no-untyped-def]
            seen.append(params)
            return await super().execute(tool_call_id, params, signal, context)

    base = ToolRegistry()
    base.register(Budget("housing_budget"))

    result = await step_registry(base, (), goal_turn=goal_turn).execute(
        "c", "housing_budget", {"cash": "1억", "regions": "서울"}, None, None
    )

    assert seen == [expected] and result.final is not goal_turn


async def test_step_returns_report_once_and_does_not_repeat_it(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    run, seen = replying(REPLY, REPLY)
    first = await runner.step(goal.id, ["housing_budget"], ["housing_profile"], run)
    runner.settle(goal.id, delivered=True)
    again = await runner.step(goal.id, ["housing_budget"], ["housing_profile"], run)
    runner.settle(goal.id, delivered=True)
    assert (first, again) == (SAID, "")
    saved = store.get(goal.id)
    assert saved is not None and saved.reported == ["2026:55A"] and saved.runs == 2
    assert [t.name for t in seen[0][1].list_all()] == ["housing_budget"]


async def test_step_free_text_or_failed_run_reports_nothing_but_counts_the_run(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    run, _ = replying("애쉬, 공고가 두 건이에요.", None)
    assert await runner.step(goal.id, [], [], run) == ""
    assert await runner.step(goal.id, [], [], run) == ""
    saved = store.get(goal.id)
    assert saved is not None and saved.runs == 2 and saved.reported == []


async def test_step_skips_paused_or_unknown_goal(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    store.save(goal.model_copy(update={"status": "paused"}))
    run, seen = replying(REPLY)
    assert await runner.step(goal.id, [], [], run) == "" and await runner.step("ghost", [], [], run) == ""
    assert seen == []


async def test_step_does_not_deliver_item_without_a_key(tmp_path):
    """'새 공고는 없어요' 같은 말은 키가 없다. 목표가 알리라고 한 것이 아니라 전하지 않는다(실측 회귀)."""
    store, runner, goal = goal_setup(tmp_path)
    run, _ = replying("머리: 애쉬.\n항목: 이번에 알릴 새 공고는 없어요\n기록: 변화 없음\n완료: 아니오")
    assert await runner.step(goal.id, [], [], run) == ""
    saved = store.get(goal.id)
    assert saved is not None and saved.notes == ["변화 없음"] and saved.reported == []


async def test_step_tells_only_the_new_one_of_two_items(tmp_path):
    """임대 1순위만 바뀌면 그것만 알린다. 모델은 지금 1순위 둘을 다 쓰고 코드가 거른다."""
    store, runner, goal = goal_setup(tmp_path)
    store.save(goal.model_copy(update={"reported": ["A:59B"]}))
    run, _ = replying(f"머리: {HEAD}\n항목: [A:59B] 분양 줄\n항목: [C:20B] 새 임대 줄\n기록: 임대 바뀜\n완료: 아니오")
    assert await runner.step(goal.id, [], [], run) == f"{HEAD}\n새 임대 줄"


async def test_step_runs_again_once_when_answered_from_notes_without_a_tool(tmp_path):
    """기록만 보고 도구 없이 답하면(현금을 몰라 하던 기록) 한 번 더 돌려 도구로 지금 상태를 보게 한다."""
    store, runner, goal = goal_setup(tmp_path)
    store.save(goal.model_copy(update={"notes": ["현금 모름"]}))
    prompts: list[str] = []

    async def lazy_then_checks(prompt, pick):  # type: ignore[no-untyped-def]
        prompts.append(prompt)
        tools = pick(registry("housing_budget"))
        if len(prompts) == 1:
            return "머리: 현금을 알려 주세요\n항목: [ask-money] 현금을 알려 주세요\n기록: 현금 모름\n완료: 아니오"
        await tools.execute("c", "housing_budget", {}, None, None)
        return REPLY

    assert await runner.step(goal.id, ["housing_budget"], [], lazy_then_checks) == SAID
    assert "- 현금 모름" in prompts[0]
    assert len(prompts) == 2 and "[다시]" in prompts[1] and "[다시]" not in prompts[0]
    # 다시 돌릴 때는 그때 기록을 보이지 않는다
    assert "- 현금 모름" not in prompts[1]
    # 도구를 부른 차례는 다시 돌리지 않는다. 혼자 쓸 도구가 없으면 다시 돌려도 소용없어 돌리지 않는다
    run, seen = replying(REPLY)
    await runner.step(goal.id, ["housing_budget"], [], run)
    toolless: list[str] = []

    async def no_tools(prompt, pick):  # type: ignore[no-untyped-def]
        toolless.append(prompt)
        return "애쉬"

    await runner.step(goal.id, [], [], no_tools)
    assert len(seen) == 1 and len(toolless) == 1


def counting(*replies: str | None, result: str = "결과"):  # type: ignore[no-untyped-def]
    """모델 차례 수를 세는 run 과, 도구를 모델 없이 부른 횟수를 세는 replay."""
    models: list[str] = []
    replays: list[tuple[str, dict]] = []
    state = {"result": result}
    queue = list(replies)

    class Budget(JarvisTool):
        name, description, parameters = "housing_budget", "", {"type": "object"}

        async def execute(self, tool_call_id, params, signal=None, context=None):  # type: ignore[no-untyped-def]
            return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                     content=[TextContent(text=state["result"])])

    async def run(prompt, pick):  # type: ignore[no-untyped-def]
        models.append(prompt)
        base = ToolRegistry()
        base.register(Budget())
        await pick(base).execute("c", "housing_budget", {"regions": ["서울"]}, None, None)
        return queue.pop(0)

    async def replay(name, params):  # type: ignore[no-untyped-def]
        replays.append((name, params))
        return state["result"]

    return run, replay, models, replays, state


async def test_step_skips_the_model_when_tool_result_did_not_change(tmp_path):
    """지난 차례 도구를 같은 인자로 다시 불러 결과가 같으면 모델을 부르지 않는다. 바뀌면 모델이 다시 판단한다."""
    store, runner, goal = goal_setup(tmp_path)
    run, replay, models, replays, state = counting(REPLY, REPLY)
    auto = ["housing_budget"]
    assert await runner.step(goal.id, auto, [], run, replay) == SAID
    runner.settle(goal.id, True)
    assert replays == [] and len(models) == 1
    saved = store.get(goal.id)
    assert saved is not None and saved.last_calls == [{"name": "housing_budget", "params": {"regions": ["서울"]}}]

    assert await runner.step(goal.id, auto, [], run, replay) == ""
    assert replays == [("housing_budget", {"regions": ["서울"]})] and len(models) == 1
    after = store.get(goal.id)
    assert after is not None and after.runs == 2 and after.notes == saved.notes

    state["result"] = "새 공고가 올라온 결과"
    assert await runner.step(goal.id, auto, [], run, replay) == ""
    assert len(models) == 2


async def test_step_does_not_skip_after_undelivered_turn(tmp_path):
    """건네지 못한 차례 뒤에는 결과가 같아도 모델을 다시 돌려 같은 항목을 다시 알린다."""
    store, runner, goal = goal_setup(tmp_path)
    run, replay, models, _, _ = counting(REPLY, REPLY)
    assert await runner.step(goal.id, ["housing_budget"], [], run, replay) == SAID
    runner.settle(goal.id, False)
    assert await runner.step(goal.id, ["housing_budget"], [], run, replay) == SAID
    assert len(models) == 2


async def test_step_runs_the_model_when_replay_fails_or_is_unavailable(tmp_path):
    """다시 부른 도구가 오류이거나 지금 쓸 수 없는 도구면 건너뛰지 않는다. 답이 없던 차례는 지문을 남기지 않는다."""
    store, runner, goal = goal_setup(tmp_path)
    run, _, models, _, _ = counting(REPLY, REPLY, REPLY, None)

    async def broken(name, params):  # type: ignore[no-untyped-def]
        return None

    await runner.step(goal.id, ["housing_budget"], [], run, broken)
    runner.settle(goal.id, True)
    await runner.step(goal.id, ["housing_budget"], [], run, broken)
    assert len(models) == 2
    await runner.step(goal.id, [], [], run, broken)
    assert len(models) == 3
    await runner.step(goal.id, ["housing_budget"], [], run, broken)
    saved = store.get(goal.id)
    assert saved is not None and saved.seen == "" and saved.last_calls == []
