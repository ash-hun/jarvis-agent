"""multi_agent: SubagentBuilder 가 정의의 도구 서브셋과 model_override 를 서브 세션에 넘기는지 검증한다."""

import pytest
from typing import Any
from unittest.mock import MagicMock

from jarvis.core.tools.builtin.read_file import ReadFileTool
from jarvis.core.multi_agent.factory import AgentDefinition
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.app.subagent_builder import SubagentBuilder
from jarvis.core.tools.builtin.bash import BashTool
from jarvis.jarvis_config import JarvisSettings
from jarvis.app.app_context import AppContext


@pytest.fixture
def captured(monkeypatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_session(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return kwargs

    monkeypatch.setattr("jarvis.core.session.AgentSession", fake_session)
    return seen


def _builder(main_registry: ToolRegistry) -> tuple[SubagentBuilder, MagicMock]:
    settings = JarvisSettings()
    ctx = AppContext(session_repo=MagicMock(), tool_registry=main_registry, settings=settings)
    services = MagicMock()
    return SubagentBuilder(ctx, services, main_registry), services


def _main_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadFileTool())
    return registry


def test_build_session_with_tools_keeps_only_known_names(captured):
    main = _main_registry()
    builder, _ = _builder(main)

    builder.build_session(AgentDefinition(name="w", description="d", tools=["read_file", "ghost"]), "agent_w")

    registry = captured["tool_registry"]
    assert registry is not main
    assert [t.name for t in registry.list_all()] == ["read_file"]
    assert captured["agent_name"] == "w" and captured["inherit_scope"] is True


def test_build_session_without_tools_shares_main_registry(captured):
    main = _main_registry()
    builder, _ = _builder(main)

    builder.build_session(AgentDefinition(name="p", description="d"), "agent_p")

    assert captured["tool_registry"] is main


def test_build_session_model_override_replaces_only_model_name(captured):
    builder, _ = _builder(_main_registry())

    builder.build_session(AgentDefinition(name="p", description="d", model_override="tiny"), "agent_p")

    model = captured["model"]
    llm = JarvisSettings().llm
    assert (model.provider, model.model, model.temperature, model.max_tokens) == (
        llm.provider, "tiny", llm.temperature, llm.max_tokens,
    )


def test_build_session_without_override_uses_app_model_config(captured):
    builder, services = _builder(_main_registry())

    builder.build_session(AgentDefinition(name="p", description="d"), "agent_p")

    assert captured["model"] is services.model_config


def test_node_tool_uses_definition_name_and_description():
    builder, _ = _builder(_main_registry())

    tool = builder.node_tool(AgentDefinition(name="planner", description="계획 세우기"), MagicMock())

    assert tool.name == "agent_planner"
    assert tool.description == "계획 세우기"
