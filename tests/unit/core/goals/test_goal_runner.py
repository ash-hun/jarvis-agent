"""목표 한 차례: 프롬프트, 경계 밖 도구 빼기, final 끄기, 이미 알린 것 막기, 꼴이 아닌 답 막기, 스케줄러와 도구 연결."""

import asyncio
from typing import Any
from datetime import datetime
from unittest.mock import MagicMock

from jarvis.core.tools.tools_registry import JarvisTool, ToolContext, ToolRegistry
from jarvis.core.goals.runner import GoalRunner, build_prompt, step_registry
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.goals.tool import GOAL_RULE, GoalTool, standing_rule
from jarvis.core.scheduler.scheduler_service import SchedulerService
from jarvis.core.goals.goals_types import Goal, goal_key
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.goals.goals_store import GoalStore
from jarvis.memory.scope import MemoryScope

NOW = datetime(2026, 10, 28, 10, 0)
TEXT = "조건 및 가장 좋은 원리금 납부액을 추천하는 공고만 알려줘"
HEAD = "애쉬, 조건에 맞고 월 부담이 가장 적은 공고예요."
REPLY = f"머리: {HEAD}\n항목: [2026:55A] 서울 행복주택, 55A 월 부담 최대 30만원\n기록: 1순위 확인\n완료: 아니오"
SAID = f"{HEAD}\n서울 행복주택, 55A 월 부담 최대 30만원"


class Final(JarvisTool):
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters = name, name, {"type": "object"}

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None,
                      context: ToolContext | None = None) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                 content=[TextContent(text="결과")], final=True)


def registry(*names: str) -> ToolRegistry:
    r = ToolRegistry()
    for n in names:
        r.register(Final(n))
    return r


def setup(tmp_path) -> tuple[GoalStore, GoalRunner, Goal]:  # type: ignore[no-untyped-def]
    store = GoalStore(str(tmp_path))
    goal, _ = store.ensure(Goal(id=goal_key("karen", TEXT), agent="karen", text=TEXT))
    return store, GoalRunner(store, now=lambda: NOW), goal


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


async def test_turn_that_answers_from_notes_without_a_tool_is_run_again_once(tmp_path):
    """기록만 보고 도구 없이 답하면(현금을 몰라 하던 기록) 한 번 더 돌려 도구로 지금 상태를 보게 한다."""
    store, runner, goal = setup(tmp_path)
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


def test_prompt_shows_goal_progress_and_boundary_but_not_what_was_reported():
    goal = Goal(id="g", agent="karen", text=TEXT, notes=["첫 확인"], reported=["2026:55A"])
    prompt = build_prompt(goal, ["housing_budget"], ["housing_profile"], NOW)
    assert TEXT in prompt and "2026-10-28 10:00" in prompt and "- 첫 확인" in prompt
    # 알렸는지는 코드가 가린다. 모델이 이 목록을 보고 새 것까지 빼거나 엉뚱한 것을 물었다
    assert "2026:55A" not in prompt
    assert "혼자 해도 되는 도구: housing_budget" in prompt and "먼저 물어야 하는 일: housing_profile" in prompt


async def test_step_tools_drop_ask_tools_and_never_end_the_turn_with_raw_results():
    tools = step_registry(registry("housing_budget", "housing_profile"), ("housing_profile",))
    assert [t.name for t in tools.list_all()] == ["housing_budget"]
    result = await tools.execute("c", "housing_budget", {}, None, ToolContext(scope=MemoryScope(user_id="u")))
    assert result.final is False and result.content[0].text == "결과"


async def test_report_is_returned_once_and_the_same_report_is_not_repeated(tmp_path):
    store, runner, goal = setup(tmp_path)
    run, seen = replying(REPLY, REPLY)
    first = await runner.step(goal.id, ["housing_budget"], ["housing_profile"], run)
    runner.settle(goal.id, delivered=True)
    again = await runner.step(goal.id, ["housing_budget"], ["housing_profile"], run)
    runner.settle(goal.id, delivered=True)
    assert (first, again) == (SAID, "")
    saved = store.get(goal.id)
    assert saved is not None and saved.reported == ["2026:55A"] and saved.runs == 2
    assert [t.name for t in seen[0][1].list_all()] == ["housing_budget"]


async def test_free_text_or_failed_run_reports_nothing_but_counts_the_run(tmp_path):
    store, runner, goal = setup(tmp_path)
    run, _ = replying("애쉬, 공고가 두 건이에요.", None)
    assert await runner.step(goal.id, [], [], run) == ""
    assert await runner.step(goal.id, [], [], run) == ""
    saved = store.get(goal.id)
    assert saved is not None and saved.runs == 2 and saved.reported == []


async def test_paused_or_unknown_goal_does_not_run(tmp_path):
    store, runner, goal = setup(tmp_path)
    store.save(goal.model_copy(update={"status": "paused"}))
    run, seen = replying(REPLY)
    assert await runner.step(goal.id, [], [], run) == "" and await runner.step("ghost", [], [], run) == ""
    assert seen == []


def _scheduler() -> SchedulerService:
    return SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=registry("housing_budget"),
                            model=MagicMock())


async def test_scheduler_goal_turn_reports_through_the_conversation_and_stays_silent_otherwise(tmp_path):
    store, runner, goal = setup(tmp_path)
    svc = _scheduler()
    svc.set_goal_runner(runner)
    spoken: list[tuple[str, str]] = []
    notices: list[dict[str, Any]] = []

    async def converse(agent: str, text: str) -> bool:
        spoken.append((agent, text))
        return True

    async def notify(payload: dict[str, Any]) -> None:
        notices.append(payload)

    svc.set_conversation(converse)
    svc.set_notifier(notify)
    replies = [REPLY, REPLY]

    async def execute(task, pick=None):  # type: ignore[no-untyped-def]
        assert task.prompt.startswith(f"[목표] {TEXT}") and pick is not None
        await pick(registry("housing_budget")).execute("c", "housing_budget", {}, None, None)
        return replies.pop(0)

    svc._execute_task = execute  # type: ignore[method-assign]
    task = ScheduledTask(name=goal.task_name, prompt=TEXT, kind="goal", args={"goal": goal.id}, agent="karen",
                         deliver="conversation")
    await svc._run_and_deliver(task)
    await svc._run_and_deliver(task)
    assert spoken == [("karen", SAID)] and notices == []
    # 둘째 차례는 도구 결과가 그대로라 스케줄러가 도구만 다시 부르고 모델을 돌리지 않았다
    assert replies == [REPLY]


async def test_goal_tool_sets_one_goal_and_one_task_and_runs_the_first_turn_once(tmp_path):
    store = GoalStore(str(tmp_path))
    svc = _scheduler()
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


async def test_conversation_delivery_needs_no_notice_channel(tmp_path):
    """알림 채널이 없어도(대화만 있어도) 목표 보고는 대화로 간다. 평가 중 보고가 사라진 회귀."""
    store, runner, goal = setup(tmp_path)
    svc = _scheduler()
    svc.set_goal_runner(runner)
    spoken: list[str] = []

    async def converse(agent: str, text: str) -> bool:
        spoken.append(text)
        return True

    async def execute(task, pick=None):  # type: ignore[no-untyped-def]
        return REPLY

    svc.set_conversation(converse)
    svc._execute_task = execute  # type: ignore[method-assign]
    await svc._run_and_deliver(goal_task_for(goal))
    assert spoken == [SAID]


def goal_task_for(goal: Goal) -> ScheduledTask:
    from jarvis.core.goals.tool import goal_task

    return goal_task(goal)


async def test_item_without_a_key_is_not_delivered(tmp_path):
    """'새 공고는 없어요' 같은 말은 키가 없다. 목표가 알리라고 한 것이 아니라 전하지 않는다(실측 회귀)."""
    store, runner, goal = setup(tmp_path)
    run, _ = replying("머리: 애쉬.\n항목: 이번에 알릴 새 공고는 없어요\n기록: 변화 없음\n완료: 아니오")
    assert await runner.step(goal.id, [], [], run) == ""
    saved = store.get(goal.id)
    assert saved is not None and saved.notes == ["변화 없음"] and saved.reported == []


async def test_when_one_of_two_items_is_new_only_that_one_is_told(tmp_path):
    """임대 1순위만 바뀌면 그것만 알린다. 모델은 지금 1순위 둘을 다 쓰고 코드가 거른다."""
    store, runner, goal = setup(tmp_path)
    store.save(goal.model_copy(update={"reported": ["A:59B"]}))
    run, _ = replying(f"머리: {HEAD}\n항목: [A:59B] 분양 줄\n항목: [C:20B] 새 임대 줄\n기록: 임대 바뀜\n완료: 아니오")
    assert await runner.step(goal.id, [], [], run) == f"{HEAD}\n새 임대 줄"


async def test_unattended_turns_drop_values_only_the_user_can_give():
    """사람이 없는 차례에서는 모델이 현금 같은 값을 지어내도 버리고 저장된 값으로 돈다(실측: 18번 중 1번 지어냄)."""
    seen: list[dict[str, Any]] = []

    class Budget(Final):
        user_only_params = ("cash",)

        async def execute(self, tool_call_id, params, signal=None, context=None):  # type: ignore[no-untyped-def]
            seen.append(params)
            return await super().execute(tool_call_id, params, signal, context)

    base = ToolRegistry()
    base.register(Budget("housing_budget"))
    await step_registry(base, ()).execute("c", "housing_budget", {"cash": "1억", "regions": "서울"}, None, None)
    assert seen == [{"regions": "서울"}]


async def test_scheduled_tasks_keep_the_values_the_user_wrote():
    seen: list[dict[str, Any]] = []

    class Budget(Final):
        user_only_params = ("cash",)

        async def execute(self, tool_call_id, params, signal=None, context=None):  # type: ignore[no-untyped-def]
            seen.append(params)
            return await super().execute(tool_call_id, params, signal, context)

    base = ToolRegistry()
    base.register(Budget("housing_budget"))
    result = await step_registry(base, (), goal_turn=False).execute("c", "housing_budget", {"cash": "1억"}, None, None)
    assert seen == [{"cash": "1억"}] and result.final is True


async def test_goal_command_sets_lists_and_stops_without_a_model(tmp_path):
    from jarvis.core.slash.goal_cmd import make_goal_handler

    svc = _scheduler()
    svc.run_soon = lambda task: None  # type: ignore[method-assign]
    handle = make_goal_handler(GoalTool(GoalStore(str(tmp_path)), svc, now=lambda: NOW))
    scope = MemoryScope(user_id="u", agent_id="karen")
    assert (await handle(TEXT, scope)).startswith(f"[Goal] 목표를 맡았다: {TEXT}")
    assert "이미 맡은 목표" in await handle(TEXT, scope)
    assert "[active]" in await handle("", scope)
    assert "멈췄다" in await handle("stop 원리금", scope)
    assert "[paused]" in await handle("", scope)


def test_goal_task_shows_its_goal_not_its_id_in_the_agenda():
    from jarvis.core.scheduler.task import task_label
    from jarvis.core.goals.tool import goal_task

    task = goal_task(Goal(id=goal_key("karen", TEXT), agent="karen", text=TEXT))
    assert task_label(task) == f"목표: {TEXT[:60]}"


async def test_items_that_could_not_be_delivered_come_again_next_turn(tmp_path):
    """대화도 알림도 못 건넨 항목은 알린 것으로 적지 않는다. 다음 차례에 다시 건넨다."""
    store, runner, goal = setup(tmp_path)
    svc = _scheduler()
    svc.set_goal_runner(runner)
    spoken: list[str] = []
    up = False

    async def converse(agent: str, text: str) -> bool:
        if up:
            spoken.append(text)
        return up

    svc.set_conversation(converse)
    replies = [REPLY, REPLY, REPLY]

    async def execute(task, pick=None):  # type: ignore[no-untyped-def]
        await pick(registry("housing_budget")).execute("c", "housing_budget", {}, None, None)
        return replies.pop(0)

    svc._execute_task = execute  # type: ignore[method-assign]
    task = ScheduledTask(name=goal.task_name, prompt=TEXT, kind="goal", args={"goal": goal.id}, agent="karen",
                         deliver="conversation")
    await svc._run_and_deliver(task)  # 대화도 알림 채널도 없다
    saved = store.get(goal.id)
    assert saved is not None and saved.reported == [] and saved.runs == 1
    up = True
    await svc._run_and_deliver(task)
    await svc._run_and_deliver(task)
    assert spoken == [SAID]
    saved = store.get(goal.id)
    assert saved is not None and saved.reported == ["2026:55A"]


def test_standing_requests_get_the_goal_rule_only_when_the_agent_can_set_goals():
    """계속 챙길 일일 수 있는 말에만 목표 규칙을 붙인다. goal 도구가 없는 에이전트에는 붙이지 않는다.
    속생각이 '바로 찾기' 를 선택지로 내면 규칙 없이는 라이브 5번 중 0번 맡았다."""
    tools = {"goal", "housing_budget"}
    standing = (TEXT, "서울에 새 행복주택 공고 나오면 알려줘", "앞으로 추천 1순위 바뀌면 알려줘", "새 공고 계속 챙겨줘")
    for text in standing:
        assert standing_rule(text, tools) == GOAL_RULE, text
    for text in ("현금 1억, 월 150으로 맞는 공고 찾아줘", "가장 추천하는 게 뭐야?"):
        assert standing_rule(text, tools) is None, text
    assert standing_rule(TEXT, {"housing_budget"}) is None



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


async def test_turn_whose_tool_result_did_not_change_skips_the_model(tmp_path):
    """지난 차례 도구를 같은 인자로 다시 불러 결과가 같으면 모델을 부르지 않는다. 바뀌면 모델이 다시 판단한다."""
    store, runner, goal = setup(tmp_path)
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


async def test_undelivered_items_are_not_skipped_next_turn(tmp_path):
    """건네지 못한 차례 뒤에는 결과가 같아도 모델을 다시 돌려 같은 항목을 다시 알린다."""
    store, runner, goal = setup(tmp_path)
    run, replay, models, _, _ = counting(REPLY, REPLY)
    assert await runner.step(goal.id, ["housing_budget"], [], run, replay) == SAID
    runner.settle(goal.id, False)
    assert await runner.step(goal.id, ["housing_budget"], [], run, replay) == SAID
    assert len(models) == 2


async def test_failed_or_unavailable_replay_runs_the_model(tmp_path):
    """다시 부른 도구가 오류이거나 지금 쓸 수 없는 도구면 건너뛰지 않는다. 답이 없던 차례는 지문을 남기지 않는다."""
    store, runner, goal = setup(tmp_path)
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
