"""scheduler 의 SchedulerService: 루프 수명, 목록과 토글, 다음 실행 시각, 실행과 알림, 에이전트 도구, 목표 차례."""

import sys
import yaml
import pytest
import asyncio
import textwrap
from typing import Any
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from tests.fixtures.goal_helpers import REPLY, SAID, TEXT, goal_scheduler, goal_setup, registry
from jarvis.model_layer.model_types import ModelConfig, TextContent, ToolResultMessage
from jarvis.core.scheduler.scheduler_service import SchedulerService, TaskAgent
from jarvis.core.tools.tools_registry import JarvisTool, ToolRegistry
from jarvis.core.scheduler.scheduler_loader import load_tasks
from jarvis.core.skills.skills_registry import SkillRegistry
from tests.fixtures.agent_registry_helpers import app_tools
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.goals.tool import goal_task


MODEL = ModelConfig(provider="faux", model="faux-model")


def _service(tasks=None, schedules_dir=None, repo=None, **deps):
    return SchedulerService(
        tasks=tasks or [],
        session_repo=repo or MagicMock(create=AsyncMock()),
        tool_registry=ToolRegistry(),
        model=MODEL,
        schedules_dir=schedules_dir,
        **deps,
    )


def _collect(svc: SchedulerService) -> AsyncMock:
    notify = AsyncMock()
    svc.set_notifier(notify)
    return notify


async def _settle() -> None:
    """run_soon 이 띄운 백그라운드 실행이 끝날 때까지 기다린다."""
    await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}))


@contextmanager
def _fake_session(prompt: AsyncMock | None = None):
    session = MagicMock(prompt=prompt or AsyncMock(return_value=MagicMock()))
    with patch("jarvis.core.session.AgentSession", return_value=session) as ctor, \
            patch("jarvis.core.policy.pipeline.SecurityPipeline"):
        yield ctor


def test_task_count_counts_enabled_only():
    svc = _service([
        ScheduledTask(name="a", schedule="0 * * * *", prompt="p", enabled=True),
        ScheduledTask(name="b", schedule="0 * * * *", prompt="p", enabled=False),
        ScheduledTask(name="c", schedule="0 * * * *", prompt="p", enabled=True),
    ])

    assert svc.task_count == 2


def test_list_tasks_includes_disabled_and_is_a_copy():
    svc = _service([
        ScheduledTask(name="a", schedule="0 * * * *", prompt="p"),
        ScheduledTask(name="b", schedule="0 * * * *", prompt="p", enabled=False),
    ])

    listed = svc.list_tasks()
    listed.clear()

    assert [t.name for t in svc.list_tasks()] == ["a", "b"]


async def test_start_is_idempotent_and_stop_ends_the_loop():
    svc = _service()
    before = asyncio.all_tasks()

    await svc.start()
    await svc.start()
    loops = asyncio.all_tasks() - before
    await svc.stop()

    assert len(loops) == 1
    assert all(t.done() for t in loops)


async def test_loop_without_croniter_still_fires_once_tasks_and_skips_cron():
    fired = asyncio.Event()
    svc = _service([
        ScheduledTask(name="cron", schedule="* * * * *", prompt="c"),
        ScheduledTask(name="once", prompt="물", kind="reminder", run_at=datetime.now() - timedelta(seconds=1)),
    ])
    notify = AsyncMock(side_effect=lambda _p: fired.set())
    svc.set_notifier(notify)

    with patch.dict(sys.modules, {"croniter": None}):
        await svc.start()
        await asyncio.wait_for(fired.wait(), 1)
        await svc.stop()

    assert [c.args[0]["name"] for c in notify.await_args_list] == ["once"]


@pytest.mark.parametrize(("left", "enabled"), [(timedelta(hours=-1), False), (timedelta(hours=5), True)])
async def test_loop_disables_task_past_run_until(left, enabled):
    task = ScheduledTask(name="t", schedule="0 * * * *", prompt="test", run_until=datetime.now() + left)
    svc = _service([task])

    await svc.start()
    for _ in range(3):
        await asyncio.sleep(0)
    await svc.stop()

    assert task.enabled is enabled


def test_set_enabled_unknown_name_returns_false():
    assert _service().set_enabled("nope", False) is False


def test_toggle_rewrites_only_enabled_in_source_yaml(tmp_path):
    path = tmp_path / "brief.yaml"
    path.write_text(textwrap.dedent("""
        name: brief
        schedule: "0 9 * * *"
        prompt: morning brief
        description: 매일 아침
        tools_allowed: [web_search]
    """))
    svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))

    assert svc.set_enabled("brief", False) is True

    data = yaml.safe_load(path.read_text())
    assert data["enabled"] is False
    assert data["description"] == "매일 아침"
    assert data["tools_allowed"] == ["web_search"]
    assert load_tasks(str(tmp_path))[0].enabled is False


def test_toggle_in_list_file_touches_only_matching_item(tmp_path):
    path = tmp_path / "many.yaml"
    path.write_text(textwrap.dedent("""
        - name: one
          schedule: "0 9 * * *"
          prompt: p1
        - name: two
          schedule: "0 10 * * *"
          prompt: p2
    """))
    svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))

    svc.set_enabled("two", False)

    items = yaml.safe_load(path.read_text())
    assert [i["name"] for i in items] == ["one", "two"]
    assert "enabled" not in items[0]
    assert items[1]["enabled"] is False


def test_toggle_is_idempotent(tmp_path):
    path = tmp_path / "brief.yaml"
    path.write_text('name: brief\nschedule: "0 9 * * *"\nprompt: p\n')
    svc = _service(load_tasks(str(tmp_path)), schedules_dir=str(tmp_path))

    svc.set_enabled("brief", False)
    first = path.read_text()
    svc.set_enabled("brief", False)

    assert path.read_text() == first


def test_added_task_is_saved_and_survives_restart(tmp_path):
    deadline = datetime.now().replace(microsecond=0) + timedelta(days=3)
    svc = _service(schedules_dir=str(tmp_path))

    svc.add_task(ScheduledTask(name="slash-1", schedule="0 * * * *", prompt="collect", run_until=deadline))

    assert svc.task_count == 1
    assert (tmp_path / "slash-1.yaml").exists()
    reloaded = load_tasks(str(tmp_path))
    assert [t.name for t in reloaded] == ["slash-1"]
    assert reloaded[0].run_until == deadline
    svc.set_enabled("slash-1", False)
    assert load_tasks(str(tmp_path))[0].enabled is False


def test_add_task_without_dir_stays_in_memory(tmp_path):
    svc = _service()

    svc.add_task(ScheduledTask(name="mem", schedule="0 * * * *", prompt="p"))

    assert svc.task_count == 1
    assert list(tmp_path.iterdir()) == []


def test_next_run_follows_cron():
    pytest.importorskip("croniter")
    task = ScheduledTask(name="t", schedule="0 9 * * *", prompt="p")

    assert SchedulerService.next_run(task, datetime(2026, 9, 24, 8, 30)) == datetime(2026, 9, 24, 9, 0)


@pytest.mark.parametrize(
    ("task", "now"),
    [
        (ScheduledTask(name="t", schedule="0 9 * * *", prompt="p", enabled=False), None),
        (ScheduledTask(name="t", schedule="0 9 * * *", prompt="p", run_until=datetime(2026, 9, 24, 8, 45)),
         datetime(2026, 9, 24, 8, 30)),
        (ScheduledTask(name="t", schedule="not a cron", prompt="p"), None),
    ],
    ids=["disabled", "after_deadline", "bad_cron"],
)
def test_next_run_is_none_when_task_cannot_run(task, now):
    pytest.importorskip("croniter")

    assert SchedulerService.next_run(task, now) is None


@pytest.mark.parametrize(
    ("given", "expected_type"),
    [({}, None), ({"plugin_runner": PluginRunner(), "skill_registry": SkillRegistry()}, "given")],
    ids=["defaults", "given"],
)
async def test_task_session_gets_plugin_runner_and_skill_registry(given, expected_type):
    svc = _service(**given)

    with _fake_session() as ctor:
        svc.run_soon(ScheduledTask(name="t", schedule="* * * * *", prompt="p"))
        await _settle()

    kwargs = ctor.call_args.kwargs
    if expected_type == "given":
        assert kwargs["plugin_runner"] is given["plugin_runner"]
        assert kwargs["skill_registry"] is given["skill_registry"]
    else:
        assert isinstance(kwargs["plugin_runner"], PluginRunner)
        assert isinstance(kwargs["skill_registry"], SkillRegistry)


@pytest.mark.parametrize(
    ("task", "once"),
    [
        (ScheduledTask(name="news", prompt="뉴스 요약", kind="task", run_at=datetime(2026, 9, 24, 19, 0)), True),
        (ScheduledTask(name="brief", schedule="0 9 * * *", prompt="뉴스 요약"), False),
    ],
    ids=["once_task", "cron_task"],
)
async def test_task_runs_prompt_in_new_session_and_delivers_answer(task, once):
    svc = _service()
    notify = _collect(svc)
    prompt = AsyncMock(return_value=MagicMock(text=lambda: "오늘의 요약"))

    with _fake_session(prompt):
        svc.run_soon(task)
        await _settle()

    prompt.assert_called_once_with("뉴스 요약")
    payload = notify.await_args[0][0]
    assert payload["text"] == "오늘의 요약" and payload["error"] is False and payload["once"] is once


async def test_failed_task_is_reported_as_error():
    svc = _service()
    notify = _collect(svc)

    with _fake_session(AsyncMock(side_effect=RuntimeError("boom"))):
        svc.run_soon(ScheduledTask(name="news", prompt="뉴스 요약", kind="task"))
        await _settle()

    assert notify.await_args[0][0]["error"] is True


async def test_task_runs_as_its_agent():
    repo = MagicMock(create=AsyncMock())
    svc = _service(repo=repo)
    karen_model = MagicMock()
    svc.set_agent_resolver(lambda a: TaskAgent(karen_model, "카렌", "karen") if a == "karen" else None)

    with _fake_session() as ctor:
        svc.run_soon(ScheduledTask(name="k", schedule="* * * * *", prompt="뉴스", agent="karen"))
        await _settle()

    kwargs = ctor.call_args.kwargs
    assert (kwargs["model"], kwargs["system_prompt"], kwargs["agent_name"]) == (karen_model, "카렌", "karen")
    assert repo.create.call_args.kwargs["agent_id"] == "karen"


async def test_task_with_unknown_agent_fails_without_running():
    svc = _service()
    notify = _collect(svc)

    with patch("jarvis.core.session.AgentSession") as ctor:
        svc.run_soon(ScheduledTask(name="g", schedule="* * * * *", prompt="x", agent="ghost"))
        await _settle()

    ctor.assert_not_called()
    assert notify.await_args[0][0]["error"] is True


@pytest.mark.parametrize("delay", [4, 1800])
async def test_due_once_reminder_fires_once_with_delay_and_is_removed(tmp_path, delay):
    now = datetime(2026, 9, 24, 19, 30, 4)
    svc = _service(schedules_dir=str(tmp_path))
    notify = _collect(svc)
    run_at = now - timedelta(seconds=delay)
    svc.add_task(ScheduledTask(name="once-1", prompt="물 마시기", kind="reminder", run_at=run_at))
    assert (tmp_path / "once-1.yaml").exists()

    await asyncio.gather(*svc._tick(now, None))

    payload = notify.await_args[0][0]
    assert payload["type"] == "reminder" and payload["text"] == "물 마시기"
    assert payload["kind"] == "reminder" and payload["once"] is True
    assert payload["delayed_sec"] == delay
    assert svc.list_tasks() == []
    assert not (tmp_path / "once-1.yaml").exists()
    assert svc._tick(now + timedelta(seconds=10), None) == []


def test_future_once_task_is_not_fired():
    now = datetime(2026, 9, 24, 18, 0)
    svc = _service([ScheduledTask(name="later", prompt="p", run_at=now + timedelta(minutes=5))])

    assert svc._tick(now, None) == []
    assert svc.next_run(svc.get_task("later")) == now + timedelta(minutes=5)


async def test_cron_slot_fires_once_across_ticks():
    croniter = pytest.importorskip("croniter").croniter
    slot = datetime(2026, 9, 24, 9, 0, 0)
    svc = _service([ScheduledTask(name="brief", schedule="0 9 * * *", prompt="브리핑")])
    notify = _collect(svc)

    with _fake_session(AsyncMock(return_value=MagicMock(text=lambda: "x"))):
        for seconds in (5, 15, 70):
            await asyncio.gather(*svc._tick(slot + timedelta(seconds=seconds), croniter))

    assert notify.await_count == 1


class _Echo(JarvisTool):
    name = "housing_watch"
    description = "x"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, texts: list[str], error: bool = False) -> None:
        self.texts, self.error, self.calls = texts, error, []

    async def execute(self, tool_call_id, params, signal=None, context=None):
        self.calls.append({"params": params, "agent": context.scope.agent_id})
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name,
                                 content=[TextContent(text=self.texts.pop(0))], is_error=self.error)


def _tool_service(tool: JarvisTool) -> tuple[SchedulerService, list[dict]]:
    agent_tools = ToolRegistry()
    agent_tools.register(tool)
    svc = _service()
    svc.set_agent_resolver(lambda a: TaskAgent(MagicMock(), None, "karen", agent_tools) if a == "karen" else None)
    sent: list[dict] = []

    async def notify(payload):
        sent.append(payload)

    svc.set_notifier(notify)
    return svc, sent


async def _run(svc: SchedulerService, task: ScheduledTask) -> None:
    svc.run_soon(task)
    await _settle()


async def test_tool_task_calls_agents_tool_and_skips_empty_text():
    tool = _Echo(["", "새 LH 공고 1건"])
    svc, sent = _tool_service(tool)
    task = ScheduledTask(name="watch", schedule="0 9 * * *", prompt="", kind="tool", tool="housing_watch",
                         args={"regions": "서울", "quiet": True}, agent="karen", description="새 공고")

    await _run(svc, task)
    assert sent == []
    await _run(svc, task)

    assert [p["text"] for p in sent] == ["새 LH 공고 1건"] and sent[0]["label"] == "watch"
    assert tool.calls[0] == {"params": {"regions": "서울", "quiet": True}, "agent": "karen"}


async def test_tool_error_or_unknown_tool_is_a_failed_notice():
    svc, sent = _tool_service(_Echo(["LH 조회 실패"], error=True))

    await _run(svc, ScheduledTask(name="w", prompt="", kind="tool", tool="housing_watch", agent="karen"))
    await _run(svc, ScheduledTask(name="g", prompt="", kind="tool", tool="ghost", agent="karen"))

    assert [p["error"] for p in sent] == [True, True]


async def test_conversation_delivery_goes_to_the_agent_and_falls_back_to_a_notice():
    svc, sent = _tool_service(_Echo(["애쉬, 새로 올라온 공고가 1건 있어요", "애쉬, 새 공고 2건", "실패", ""]))
    spoken: list[tuple[str, str]] = []
    joined = [True, False]

    async def converse(agent, text):
        spoken.append((agent, text))
        return joined.pop(0)

    svc.set_conversation(converse)
    task = ScheduledTask(name="rt", prompt="", kind="tool", tool="housing_watch", agent="karen",
                         deliver="conversation")

    await _run(svc, task)
    assert spoken == [("karen", "애쉬, 새로 올라온 공고가 1건 있어요")] and sent == []
    await _run(svc, task)
    assert [p["text"] for p in sent] == ["애쉬, 새 공고 2건"]
    await _run(svc, task.model_copy(update={"deliver": "notice"}))
    await _run(svc, task)
    assert len(spoken) == 2 and len(sent) == 2


def _scheduler(tools: ToolRegistry) -> SchedulerService:
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_messages = AsyncMock(return_value=[])
    svc = SchedulerService(tasks=[], session_repo=repo, tool_registry=ToolRegistry(), model=MagicMock())
    svc.set_agent_resolver(lambda a: TaskAgent(MagicMock(), "p", "karen", tools, ("housing_profile",)))
    return svc


async def test_unattended_task_runs_without_ask_tools():
    svc = _scheduler(app_tools("lh_notice", "housing_profile"))
    session = MagicMock()
    session.prompt = AsyncMock(return_value=None)

    with patch("jarvis.core.session.AgentSession", return_value=session) as ctor:
        await svc._execute_task(ScheduledTask(name="t", prompt="공고 확인", agent="karen"))

    names = [t.name for t in ctor.call_args.kwargs["tool_registry"].list_all()]
    assert names == ["lh_notice"]


async def test_goal_turn_lists_ask_tools_and_never_makes_goals_or_schedules():
    svc = _scheduler(app_tools("lh_notice", "housing_profile", "goal", "schedule"))
    runner = MagicMock()
    runner.step = AsyncMock(return_value="")
    svc.set_goal_runner(runner)

    await svc._execute_goal(ScheduledTask(name="goal-x", prompt="g", kind="goal", args={"goal": "x"}, agent="karen"))

    _, auto, ask, _, _ = runner.step.call_args.args
    assert auto == ["lh_notice"] and ask == ["goal", "housing_profile", "schedule"]


async def test_goal_turn_reports_through_the_conversation_and_stays_silent_otherwise(tmp_path):
    store, runner, goal = goal_setup(tmp_path)
    svc = goal_scheduler()
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


async def test_goal_turn_conversation_delivery_needs_no_notice_channel(tmp_path):
    """알림 채널이 없어도(대화만 있어도) 목표 보고는 대화로 간다. 평가 중 보고가 사라진 회귀."""
    store, runner, goal = goal_setup(tmp_path)
    svc = goal_scheduler()
    svc.set_goal_runner(runner)
    spoken: list[str] = []

    async def converse(agent: str, text: str) -> bool:
        spoken.append(text)
        return True

    async def execute(task, pick=None):  # type: ignore[no-untyped-def]
        return REPLY

    svc.set_conversation(converse)
    svc._execute_task = execute  # type: ignore[method-assign]
    await svc._run_and_deliver(goal_task(goal))
    assert spoken == [SAID]


async def test_goal_turn_undelivered_items_come_again_next_turn(tmp_path):
    """대화도 알림도 못 건넨 항목은 알린 것으로 적지 않는다. 다음 차례에 다시 건넨다."""
    store, runner, goal = goal_setup(tmp_path)
    svc = goal_scheduler()
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
