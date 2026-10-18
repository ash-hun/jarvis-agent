"""ToolLoader(파일 기반 도구 로딩)와 JarvisTool 기반 클래스 테스트."""

import pytest

from jarvis.core.tools.loader import ToolLoader, looks_like_tool
from jarvis.core.tools.registry import JarvisTool, ToolRegistry
from jarvis.core.tools.builtin.web_search import WebSearchTool
from jarvis.core.tools.builtin.bash import BashTool

DUCK_TOOL = """
class DuckTool:
    name = "duck"
    description = "quacks"
    parameters = {"type": "object", "properties": {}}
    execution_mode = "sequential"

    async def execute(self, tool_call_id, params, signal=None):
        return None
"""

FUNCTION_TOOL = """
TOOL_DESCRIPTION = "adds"

async def execute(tool_call_id, params):
    return {"content": str(params["a"] + params["b"])}
"""


class TestJarvisTool:
    async def test_execute_has_no_default(self):
        with pytest.raises(NotImplementedError):
            await JarvisTool().execute("c1", {})

    def test_default_execution_mode_is_parallel(self):
        assert JarvisTool.execution_mode == "parallel"

    def test_builtins_inherit(self):
        assert isinstance(BashTool(), JarvisTool)
        assert isinstance(WebSearchTool(), JarvisTool)


class TestLooksLikeTool:
    def test_duck_typed_object(self):
        class Duck:
            name = "d"
            description = ""
            parameters: dict = {}
            execution_mode = "parallel"

            async def execute(self, *a, **k): ...

        assert looks_like_tool(Duck())

    def test_missing_member(self):
        class NoMode:
            name = "d"
            description = ""
            parameters: dict = {}

            async def execute(self, *a, **k): ...

        assert not looks_like_tool(NoMode())

    def test_execute_none_is_not_a_tool(self):
        class Nulled:
            name = "d"
            description = ""
            parameters: dict = {}
            execution_mode = "parallel"
            execute = None

        assert not looks_like_tool(Nulled())


class TestToolLoader:
    async def test_missing_directory(self, tmp_path):
        assert await ToolLoader(ToolRegistry()).load_directory(str(tmp_path / "nope")) == []

    async def test_loads_duck_typed_class(self, tmp_path):
        (tmp_path / "duck_tool_mod.py").write_text(DUCK_TOOL)
        registry = ToolRegistry()
        assert await ToolLoader(registry).load_directory(str(tmp_path)) == ["duck"]
        assert registry.get("duck").execution_mode == "sequential"

    async def test_loads_execute_function(self, tmp_path):
        (tmp_path / "add_numbers.py").write_text(FUNCTION_TOOL)
        registry = ToolRegistry()
        assert await ToolLoader(registry).load_directory(str(tmp_path)) == ["add-numbers"]
        tool = registry.get("add-numbers")
        assert tool.description == "adds"
        assert tool.parameters == {"type": "object", "properties": {}}
        result = await tool.execute("c1", {"a": 1, "b": 2})
        assert result.content[0].text == "3"
        assert not result.is_error

    async def test_function_error_becomes_error_result(self, tmp_path):
        (tmp_path / "add_numbers2.py").write_text(FUNCTION_TOOL)
        registry = ToolRegistry()
        await ToolLoader(registry).load_directory(str(tmp_path))
        result = await registry.get("add-numbers2").execute("c1", {})
        assert result.is_error

    async def test_yaml_metadata_with_handler(self, tmp_path):
        (tmp_path / "greet_mod.yaml").write_text("name: greet\ndescription: says hi\nexecution_mode: sequential\n")
        (tmp_path / "greet_mod.py").write_text("async def execute(tool_call_id, params):\n    return 'hi'\n")
        registry = ToolRegistry()
        assert await ToolLoader(registry).load_directory(str(tmp_path)) == ["greet"]
        tool = registry.get("greet")
        assert tool.execution_mode == "sequential"
        assert (await tool.execute("c1", {})).content[0].text == "hi"

    async def test_reload_is_idempotent(self, tmp_path):
        (tmp_path / "duck_tool_mod2.py").write_text(DUCK_TOOL)
        registry = ToolRegistry()
        loader = ToolLoader(registry)
        await loader.load_directory(str(tmp_path))
        await loader.load_directory(str(tmp_path))
        assert [t.name for t in registry.list_all()] == ["duck"]

    async def test_broken_file_is_logged(self, tmp_path, capsys):
        (tmp_path / "broken_tool_mod.py").write_text("raise RuntimeError('nope')\n")
        assert await ToolLoader(ToolRegistry()).load_directory(str(tmp_path)) == []
        assert "[ToolLoader] Failed to load broken_tool_mod.py: nope" in capsys.readouterr().out
