"""SessionBuilder.thought_parts 단위 테스트 — A1 모델 분리 / A2 싱크 / A3 composer."""

from unittest.mock import MagicMock

from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    InterpretationOnlyComposer,
)
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.app.session_builder import SessionBuilder
from jarvis.app.agent_profile import AgentProfile
from jarvis.model_layer.types import ModelConfig
from jarvis.app.app_services import AppServices
from jarvis.app.app_context import AppContext
from jarvis.config import JarvisSettings


def _ctx(**thought_overrides) -> AppContext:
    settings = JarvisSettings()
    settings.thought.enabled = True
    for k, v in thought_overrides.items():
        setattr(settings.thought, k, v)
    return AppContext(session_repo=None, tool_registry=None, settings=settings)


def _extra() -> dict:
    return {
        "memory": MemoryService(InMemoryItemStore()),
    }


_MAIN = ModelConfig(provider="anthropic", model="claude", api_key="mainkey", base_url="")


def _build_thought(ctx: AppContext, extra: dict, main: ModelConfig) -> tuple:
    """옛 _build_thought(ctx, extra, main) 모양으로 SessionBuilder.thought_parts 를 부른다(테스트 본문 유지용)."""
    services = AppServices(
        pipeline=MagicMock(),
        plugin_runner=MagicMock(),
        skill_registry=MagicMock(),
        sandbox=MagicMock(),
        approval_rules=MagicMock(),
        memory=extra["memory"],
        model_config=main,
        activity_clock=MagicMock(),
    )
    profile = AgentProfile.main(ctx.settings, main, feedback_learner=MagicMock())
    parts = SessionBuilder(ctx, services, profile).thought_parts(services)
    return parts.engine, parts.log, parts.composer


def test_disabled_returns_all_none():
    settings = JarvisSettings()
    settings.thought.enabled = False  # 명시적으로 끔
    ctx = AppContext(session_repo=None, tool_registry=None, settings=settings)
    assert _build_thought(ctx, _extra(), _MAIN) == (None, None, None)


# ── A1: 사고 모델 provider/key/base_url 분리 ──────────────────────────────────


def test_thought_model_inherits_main_when_unset():
    engine, _, _ = _build_thought(_ctx(), _extra(), _MAIN)
    assert engine._model.provider == "anthropic"
    assert engine._model.model == "claude"
    assert engine._model.api_key == "mainkey"


def test_thought_model_fully_separated():
    from pydantic import SecretStr

    engine, _, _ = _build_thought(
        _ctx(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434",
            api_key=SecretStr("thoughtkey"),
        ),
        _extra(),
        _MAIN,
    )
    assert engine._model.provider == "ollama"
    assert engine._model.model == "llama3"
    assert engine._model.base_url == "http://localhost:11434"
    assert engine._model.api_key == "thoughtkey"


def test_thought_model_partial_override_keeps_main_key():
    # provider/model만 바꾸고 키는 비우면 메인 키 상속.
    engine, _, _ = _build_thought(_ctx(provider="ollama", model="llama3"), _extra(), _MAIN)
    assert engine._model.provider == "ollama"
    assert engine._model.api_key == "mainkey"


# ── A2: log_sinks 선택 ────────────────────────────────────────────────────────


def test_default_sink_is_ltm_only():
    _, log, _ = _build_thought(_ctx(), _extra(), _MAIN)
    assert len(log._sinks) == 1


def test_both_sinks_selected():
    _, log, _ = _build_thought(_ctx(log_sinks=["ltm", "stm"]), _extra(), _MAIN)
    assert len(log._sinks) == 2


def test_unknown_sink_ignored():
    _, log, _ = _build_thought(_ctx(log_sinks=["ltm", "bogus"]), _extra(), _MAIN)
    assert len(log._sinks) == 1


# ── A3: composer 선택 ─────────────────────────────────────────────────────────


def test_default_composer_selected():
    _, _, composer = _build_thought(_ctx(), _extra(), _MAIN)
    assert isinstance(composer, DefaultThoughtComposer)


def test_interpretation_only_composer_selected():
    _, _, composer = _build_thought(_ctx(composer="interpretation_only"), _extra(), _MAIN)
    assert isinstance(composer, InterpretationOnlyComposer)


def test_unknown_composer_falls_back_to_default():
    _, _, composer = _build_thought(_ctx(composer="nope"), _extra(), _MAIN)
    assert isinstance(composer, DefaultThoughtComposer)


# ── 최상위 에이전트별 세션 ──────────────────────────────────────────────────────


def _agent_session(profile_kwargs: dict, tmp_path, agent_tools=None):
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    from jarvis.core.tools.builtin.read_file import ReadFileTool
    from jarvis.core.tools.builtin.glob import GlobTool
    from jarvis.core.tools.registry import ToolRegistry

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
    assert session._tool_registry is registry


def test_agent_session_uses_its_prompt_tools_and_scope(tmp_path):
    session, registry = _agent_session(
        {"agent_id": "karen", "system_prompt": "카렌", "tools": ("read_file", "missing_tool")}, tmp_path
    )
    assert session.memory_scope.agent_id == "karen"
    assert session._harness._system_prompt == "카렌"
    # 정의의 도구만, 앱에 없는 이름은 조용히 빠진다
    assert [t.name for t in session._tool_registry.list_all()] == ["read_file"]
    assert session._tool_registry is not registry


def _housing_registry():
    from jarvis.core.tools.housing import housing_tools
    from jarvis.core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in housing_tools():
        registry.register(tool)
    return registry


def test_agent_picks_agent_only_tools_by_name(tmp_path):
    session, _ = _agent_session(
        {"agent_id": "karen", "tools": ("read_file", "lh_notice", "housing_loan")}, tmp_path, _housing_registry()
    )
    assert [t.name for t in session._tool_registry.list_all()] == ["read_file", "lh_notice", "housing_loan"]


def test_main_does_not_see_agent_only_tools(tmp_path):
    session, registry = _agent_session({}, tmp_path, _housing_registry())
    assert session._tool_registry is registry
    assert registry.get("lh_notice") is None


def test_every_agent_gets_the_task_pattern_tool(tmp_path):
    from jarvis.core.tools.task_pattern import TaskPatternTool
    from jarvis.core.tools.registry import ToolRegistry

    session, registry = _agent_session({"agent_id": "karen", "tools": ("read_file",)}, tmp_path)
    assert "remember_task_pattern" not in [t.name for t in session._tool_registry.list_all()]

    with_tool = ToolRegistry()
    with_tool.register(TaskPatternTool(MagicMock()))
    session, _ = _agent_session({"agent_id": "karen", "tools": ("read_file",)}, tmp_path, with_tool)
    assert "remember_task_pattern" in [t.name for t in session._tool_registry.list_all()]
