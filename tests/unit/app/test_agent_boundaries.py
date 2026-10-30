"""경계: never 도구는 어디서도 안 보이고, ask 도구는 스스로 하는 차례(스케줄 작업, 목표, 먼저 해 두기)에서 빠진다."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.core.tools.registry import JarvisTool, ToolContext, ToolRegistry, PickedToolRegistry
from jarvis.app.agent_registry import AgentRegistry, load_agent_specs, profile_from_spec
from jarvis.core.scheduler.service import SchedulerService, TaskAgent
from jarvis.model_layer.types import ModelConfig, ToolResultMessage
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.app.agent_profile import AgentProfile
from jarvis.app.app_context import AppContext
from jarvis.config import JarvisSettings

SPEC = """
name: K.A.R.E.N.
tools: [lh_notice, housing_profile, read_file, schedule]
boundaries:
  ask: [housing_profile]
  never: [read_file]
"""


class Named(JarvisTool):
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters = name, name, {"type": "object"}

    async def execute(self, tool_call_id: str, params: dict[str, Any], signal: asyncio.Event | None = None,
                      context: ToolContext | None = None) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name, content=[], final=True)


def app_tools(*names: str) -> ToolRegistry:
    r = ToolRegistry()
    for n in names:
        r.register(Named(n))
    return r


def registry(tmp_path, spec: str = SPEC) -> AgentRegistry:  # type: ignore[no-untyped-def]
    (tmp_path / "karen.yaml").write_text(spec)
    ctx = AppContext(session_repo=MagicMock(), tool_registry=app_tools("lh_notice", "housing_profile", "read_file",
                                                                       "schedule", "bash"),
                     settings=JarvisSettings())
    ctx.agent_tools = ToolRegistry()
    main = AgentProfile.main(JarvisSettings(), ModelConfig(provider="faux", model="m"), MagicMock())
    return AgentRegistry.load(ctx, MagicMock(), main, str(tmp_path))


def test_spec_boundaries_reach_the_profile(tmp_path):
    (tmp_path / "karen.yaml").write_text(SPEC)
    main = AgentProfile.main(JarvisSettings(), ModelConfig(provider="faux", model="m"), MagicMock())
    karen = profile_from_spec("karen", load_agent_specs(str(tmp_path))["karen"], main)
    assert (karen.ask_tools, karen.never_tools) == (("housing_profile",), ("read_file",))


def test_never_tools_are_not_visible_even_when_listed(tmp_path):
    names = {t.name for t in registry(tmp_path).builder("karen").tool_registry().list_all()}
    assert "read_file" not in names and {"lh_notice", "housing_profile", "schedule"} <= names


def test_never_tools_are_cut_from_the_whole_app_registry_when_no_tools_are_listed(tmp_path):
    spec = "name: SCOUT\nboundaries:\n  never: [bash]\n"
    names = {t.name for t in registry(tmp_path, spec).builder("karen").tool_registry().list_all()}
    assert "bash" not in names and "lh_notice" in names


def test_picked_registry_excludes_by_name_and_prefix():
    picked = PickedToolRegistry((app_tools("a", "p_x", "p_y"),), ("a",), prefixes=("p_",), exclude=("p_y",))
    assert [t.name for t in picked.list_all()] == ["a", "p_x"] and picked.get("p_y") is None


def test_task_agent_carries_ask_tools(tmp_path):
    agent = registry(tmp_path).task_agent("karen")
    assert agent is not None and agent.ask_tools == ("housing_profile",)


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


async def test_autonomous_actions_skip_ask_tools():
    from jarvis.core.session import AUTONOMOUS_SAFE_TOOLS, AgentSession
    from jarvis.core.proactive.types import ProactiveAction

    tool = sorted(AUTONOMOUS_SAFE_TOOLS)[0]
    session = AgentSession.__new__(AgentSession)
    session._ask_tools = frozenset({tool})
    session._security = MagicMock()
    session._security.sandbox.is_approval_required.return_value = False
    session._tool_registry = MagicMock()
    session._tool_registry.execute = AsyncMock()
    done = await session._execute_autonomous([ProactiveAction(kind="tool", tool_name=tool, description="d")])
    assert done == "" and not session._tool_registry.execute.called
