"""[core] 고친 동작 고정: 스케줄러 기본 의존성, 사용자 도구 모듈 이름, 스킬 필드 검사, 계층 오케스트레이터 실패 전파."""

import json as real_json
import sys
from unittest.mock import MagicMock

import pytest

from jarvis.core.multi_agent.orchestrators.hierarchical import HierarchicalOrchestrator
from jarvis.core.multi_agent.task import AgentResult, AgentTask
from jarvis.core.multi_agent.topologies.hierarchical import HierarchicalTopology
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.scheduler.service import SchedulerService
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.tools.loader import ToolLoader
from jarvis.core.tools.registry import ToolRegistry


def test_scheduler_without_deps_gets_empty_runner_and_registry():
    svc = SchedulerService(tasks=[], session_repo=MagicMock(), tool_registry=MagicMock(), model=MagicMock())
    assert isinstance(svc._plugin_runner, PluginRunner)
    assert isinstance(svc._skill_registry, SkillRegistry)


def test_scheduler_keeps_given_deps():
    runner, skills = PluginRunner(), SkillRegistry()
    svc = SchedulerService(
        tasks=[], session_repo=MagicMock(), tool_registry=MagicMock(), model=MagicMock(),
        plugin_runner=runner, skill_registry=skills,
    )
    assert svc._plugin_runner is runner and svc._skill_registry is skills


@pytest.mark.asyncio
async def test_user_tool_named_like_stdlib_does_not_shadow_it(tmp_path):
    (tmp_path / "json.py").write_text(
        'TOOL_NAME = "json_tool"\n'
        'async def execute(params, context=None):\n'
        '    return "ok"\n'
    )
    registry = ToolRegistry()
    await ToolLoader(registry).load_directory(str(tmp_path))

    assert registry.get("json_tool") is not None
    assert sys.modules["json"] is real_json


@pytest.mark.asyncio
async def test_skill_files_with_bad_field_types_are_skipped(tmp_path):
    (tmp_path / "good.md").write_text("---\nname: good\naliases: g\n---\n본문")
    (tmp_path / "bad_name.md").write_text("---\nname: 123\n---\n본문")
    (tmp_path / "bad_aliases.yaml").write_text("name: x\naliases: {a: 1}\ncontent: c\n")
    registry = SkillRegistry()

    loaded = await registry.load_directory(str(tmp_path))

    assert loaded == ["good"]
    skill = registry.get("g")
    assert skill is not None and skill.aliases == ["g"]


def _node(name: str, success: bool) -> MagicMock:
    node = MagicMock()
    node.name = name
    node.capabilities = []

    async def invoke(task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_name=name, content=name, success=success,
                           error=None if success else f"{name} failed")

    node.invoke = invoke
    return node


@pytest.mark.asyncio
async def test_hierarchical_reports_failure_of_an_earlier_level():
    topo = HierarchicalTopology()
    topo.add_node(_node("planner", success=False), level=0)
    topo.add_node(_node("writer", success=True), level=1)

    result = await HierarchicalOrchestrator(topo).dispatch(AgentTask.create("task"))

    assert not result.success
    assert result.error == "planner failed"
    assert result.content == "writer"
