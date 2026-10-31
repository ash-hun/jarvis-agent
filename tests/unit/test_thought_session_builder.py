"""thought 의 SessionBuilder: 사고 모델 분리, 로그 싱크와 composer 선택, 에이전트별 세션 조립을 검증한다."""

import pytest
from pydantic import SecretStr
from unittest.mock import MagicMock

from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    InterpretationOnlyComposer,
    ThoughtFrame,
    ThoughtRequest,
)
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.core.tools.builtin.read_file import ReadFileTool
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.thought import engine as engine_mod
from jarvis.core.tools.task_pattern import TaskPatternTool
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.memory.memory_service import MemoryService
from jarvis.model_layer.model_types import ModelConfig
from jarvis.app.session_builder import SessionBuilder
from jarvis.core.tools.builtin.glob import GlobTool
from jarvis.core.tools.housing import housing_tools
from tests.fixtures.thought_helpers import fake_llm
from jarvis.app.agent_profile import AgentProfile
from jarvis.app.app_services import AppServices
from jarvis.jarvis_config import JarvisSettings
from jarvis.app.app_context import AppContext
from jarvis.memory.scope import MemoryScope

def _ctx(**thought_overrides) -> AppContext:
    settings = JarvisSettings()
    settings.thought.enabled = True
    for k, v in thought_overrides.items():
        setattr(settings.thought, k, v)
    return AppContext(session_repo=None, tool_registry=None, settings=settings)


_MAIN = ModelConfig(provider="anthropic", model="claude", api_key="mainkey", base_url="")


def _build_thought(ctx: AppContext, memory: MemoryService | None = None) -> tuple:
    services = AppServices(
        pipeline=MagicMock(),
        plugin_runner=MagicMock(),
        skill_registry=MagicMock(),
        sandbox=MagicMock(),
        approval_rules=MagicMock(),
        memory=memory or MemoryService(InMemoryItemStore()),
        model_config=_MAIN,
        activity_clock=MagicMock(),
    )
    profile = AgentProfile.main(ctx.settings, _MAIN, feedback_learner=MagicMock())
    parts = SessionBuilder(ctx, services, profile).thought_parts(services)
    return parts.engine, parts.log, parts.composer


def test_thought_parts_all_none_when_disabled():
    settings = JarvisSettings()
    settings.thought.enabled = False
    ctx = AppContext(session_repo=None, tool_registry=None, settings=settings)

    assert _build_thought(ctx) == (None, None, None)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, {"provider": "anthropic", "model": "claude", "api_key": "mainkey"}),
        (
            {
                "provider": "ollama",
                "model": "llama3",
                "base_url": "http://localhost:11434",
                "api_key": SecretStr("thoughtkey"),
            },
            {"provider": "ollama", "model": "llama3", "base_url": "http://localhost:11434", "api_key": "thoughtkey"},
        ),
        ({"provider": "ollama", "model": "llama3"}, {"provider": "ollama", "api_key": "mainkey"}),
    ],
    ids=["inherits_main", "fully_separated", "partial_keeps_main_key"],
)
async def test_thought_parts_engine_calls_thought_model(monkeypatch, overrides, expected):
    calls = fake_llm(monkeypatch, engine_mod, reply='{"decision": "silent"}')
    engine, _, _ = _build_thought(_ctx(**overrides))

    await engine.think(ThoughtRequest(user_input="오늘 일정 정리해줘"))

    model = calls.models[0]
    assert {k: getattr(model, k) for k in expected} == expected


@pytest.mark.parametrize(
    ("log_sinks", "ltm", "notes"),
    [(None, 1, 0), (["ltm", "stm"], 1, 1), (["ltm", "bogus"], 1, 0)],
    ids=["default_ltm_only", "both", "unknown_ignored"],
)
async def test_thought_parts_log_writes_to_selected_sinks(log_sinks, ltm, notes):
    memory = MemoryService(InMemoryItemStore())
    scope = MemoryScope(user_id="local", session_id="s1")
    _, log, _ = _build_thought(_ctx(**({"log_sinks": log_sinks} if log_sinks else {})), memory)

    await log.store(ThoughtFrame(interpretation="y"), scope)

    assert len(await memory.recent(scope, limit=10)) == ltm
    assert len((await memory.working_state(scope)).notes) == notes


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (None, DefaultThoughtComposer),
        ("interpretation_only", InterpretationOnlyComposer),
        ("nope", DefaultThoughtComposer),
    ],
    ids=["default", "interpretation_only", "unknown_falls_back"],
)
def test_thought_parts_selects_composer(name, expected):
    _, _, composer = _build_thought(_ctx(**({"composer": name} if name else {})))

    assert isinstance(composer, expected)


def _agent_session(profile_kwargs: dict, tmp_path, agent_tools=None):
    settings = JarvisSettings()
    settings.thought.enabled = False
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(GlobTool())
    ctx = AppContext(
        session_repo=JsonlSessionRepo(str(tmp_path)), tool_registry=registry, settings=settings, agent_tools=agent_tools
    )
    services = AppServices(
        pipeline=MagicMock(),
        plugin_runner=MagicMock(),
        skill_registry=MagicMock(),
        sandbox=MagicMock(),
        approval_rules=MagicMock(),
        memory=MagicMock(),
        model_config=_MAIN,
        activity_clock=MagicMock(),
    )
    main = AgentProfile.main(settings, _MAIN, feedback_learner=MagicMock())
    profile = AgentProfile(**{**main.__dict__, **profile_kwargs})
    return SessionBuilder(ctx, services, profile).build("s1"), registry


def test_main_session_keeps_main_scope_and_all_tools(tmp_path):
    session, registry = _agent_session({}, tmp_path)

    assert session.memory_scope.agent_id == "main"
    assert session.agent_name is None
    assert session.tool_registry is registry


def test_agent_session_uses_its_prompt_tools_and_scope(tmp_path):
    session, registry = _agent_session(
        {"agent_id": "karen", "system_prompt": "카렌", "tools": ("read_file", "missing_tool")}, tmp_path
    )

    assert session.memory_scope.agent_id == "karen"
    assert session._harness._system_prompt == "카렌"
    # 정의의 도구만, 앱에 없는 이름은 조용히 빠진다
    assert [t.name for t in session.tool_registry.list_all()] == ["read_file"]
    assert session.tool_registry is not registry


def _housing_registry():
    registry = ToolRegistry()
    for tool in housing_tools():
        registry.register(tool)
    return registry


def test_agent_session_picks_agent_only_tools_by_name(tmp_path):
    session, _ = _agent_session(
        {"agent_id": "karen", "tools": ("read_file", "lh_notice", "housing_loan")}, tmp_path, _housing_registry()
    )

    assert [t.name for t in session.tool_registry.list_all()] == ["read_file", "lh_notice", "housing_loan"]


def test_main_session_does_not_see_agent_only_tools(tmp_path):
    session, registry = _agent_session({}, tmp_path, _housing_registry())

    assert session.tool_registry is registry
    assert registry.get("lh_notice") is None


def test_agent_gets_task_pattern_tool_only_when_app_has_it(tmp_path):
    session, registry = _agent_session({"agent_id": "karen", "tools": ("read_file",)}, tmp_path)
    assert "remember_task_pattern" not in [t.name for t in session.tool_registry.list_all()]

    with_tool = ToolRegistry()
    with_tool.register(TaskPatternTool(MagicMock()))
    session, _ = _agent_session({"agent_id": "karen", "tools": ("read_file",)}, tmp_path, with_tool)
    assert "remember_task_pattern" in [t.name for t in session.tool_registry.list_all()]
