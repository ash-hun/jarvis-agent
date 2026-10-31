"""tools 의 ToolRegistry: 등록 규칙, 조회와 실행, Picked 창과 제외 목록, JarvisTool 기본값, context 전달 여부."""

import pytest

from jarvis.core.tools.tools_registry import JarvisTool, PickedToolRegistry, ToolRegistry, accepts_context
from jarvis.model_layer.model_types import TextContent, ToolResultMessage
from jarvis.core.tools.builtin.web_search import WebSearchTool
from tests.fixtures.agent_registry_helpers import app_tools
from jarvis.core.tools.builtin.bash import BashTool


class Plain:
    async def execute(self, tool_call_id, params, signal=None): ...


class Aware:
    async def execute(self, tool_call_id, params, signal=None, context=None): ...


class _Tool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name, self.description, self.parameters, self.execution_mode = name, description or name, {}, "parallel"

    async def execute(self, tool_call_id, params, signal=None):  # type: ignore[no-untyped-def]
        return ToolResultMessage(
            tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text=f"executed with {params}")]
        )


def test_accepts_context_only_for_execute_with_context_param():
    assert accepts_context(Plain()) is False
    assert accepts_context(Aware()) is True


def test_registry_gets_lists_and_unregisters_a_tool():
    registry = ToolRegistry()
    registry.register(_Tool("mock-tool"))

    assert registry.get("mock-tool").name == "mock-tool"
    assert len(registry.list_all()) == 1
    assert [t.name for t in registry.to_llm_tools()] == ["mock-tool"]

    registry.unregister("mock-tool")

    assert registry.get("mock-tool") is None


def test_register_keeps_first_and_register_force_overwrites():
    registry = ToolRegistry()

    registry.register(_Tool("t", "v1"))
    registry.register(_Tool("t", "v2"))
    assert registry.get("t").description == "v1"

    registry.register_force(_Tool("t", "v2"))
    assert registry.get("t").description == "v2"


@pytest.mark.parametrize(
    ("name", "is_error", "text"), [("mock-tool", False, "executed"), ("ghost-tool", True, "not found")]
)
async def test_execute_runs_tool_or_reports_not_found(name, is_error, text):
    registry = ToolRegistry()
    registry.register(_Tool("mock-tool"))

    result = await registry.execute("call_01", name, {"key": "val"})

    assert result.is_error is is_error
    assert text in result.content[0].text


def test_picked_registry_sees_tools_registered_after_it_was_made():
    app, opt_in = ToolRegistry(), ToolRegistry()
    app.register(_Tool("lh_notice"))
    app.register(_Tool("bash"))
    opt_in.register(_Tool("ask_agent"))
    picked = PickedToolRegistry((app, opt_in), ("lh_notice", "ask_agent"), prefixes=("procedure_",))
    assert [t.name for t in picked.list_all()] == ["lh_notice", "ask_agent"]

    app.register(_Tool("procedure_weekly-report"))  # 세션을 만든 뒤 승인된 절차
    picked.register(_Tool("focus_note"))  # 세션이 직접 더한 도구

    names = [t.name for t in picked.to_llm_tools()]
    assert names == ["lh_notice", "ask_agent", "procedure_weekly-report", "focus_note"]
    assert picked.get("bash") is None  # 정의에 없는 도구는 계속 안 보인다
    app.unregister("procedure_weekly-report")
    assert picked.get("procedure_weekly-report") is None


async def test_jarvis_tool_base_has_no_execute_and_runs_in_parallel():
    assert JarvisTool.execution_mode == "parallel"
    assert isinstance(BashTool(), JarvisTool) and isinstance(WebSearchTool(), JarvisTool)
    with pytest.raises(NotImplementedError):
        await JarvisTool().execute("c1", {})


def test_picked_registry_excludes_by_name_and_prefix():
    picked = PickedToolRegistry((app_tools("a", "p_x", "p_y"),), ("a",), prefixes=("p_",), exclude=("p_y",))

    assert [t.name for t in picked.list_all()] == ["a", "p_x"] and picked.get("p_y") is None
