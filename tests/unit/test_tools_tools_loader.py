"""tools 의 파일 기반 도구 로더: 클래스, 함수, YAML 도구 등록과 깨진 파일, 표준 모듈 이름을 검증한다."""

import sys
import pytest
import json as real_json

from jarvis.core.tools.tools_loader import ToolLoader, looks_like_tool
from jarvis.core.tools.tools_registry import ToolRegistry

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


class _Duck:
    name, description, parameters, execution_mode = "d", "", {}, "parallel"

    async def execute(self, *a, **k): ...  # type: ignore[no-untyped-def]


class _NoMode:
    name, description, parameters = "d", "", {}

    async def execute(self, *a, **k): ...  # type: ignore[no-untyped-def]


class _Nulled:
    name, description, parameters, execution_mode = "d", "", {}, "parallel"
    execute = None


@pytest.mark.parametrize(("obj", "expected"), [(_Duck(), True), (_NoMode(), False), (_Nulled(), False)])
def test_looks_like_tool_needs_every_member_and_a_callable_execute(obj, expected):
    assert looks_like_tool(obj) is expected


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


async def test_load_directory_missing_directory_loads_nothing(tmp_path):
    assert await ToolLoader(ToolRegistry()).load_directory(str(tmp_path / "nope")) == []


async def test_load_directory_registers_duck_typed_class_once_across_reloads(tmp_path):
    (tmp_path / "duck_tool_mod.py").write_text(DUCK_TOOL)
    registry = ToolRegistry()
    loader = ToolLoader(registry)

    assert await loader.load_directory(str(tmp_path)) == ["duck"]
    await loader.load_directory(str(tmp_path))

    assert [t.name for t in registry.list_all()] == ["duck"]
    assert registry.get("duck").execution_mode == "sequential"


async def test_load_directory_wraps_execute_function_and_its_errors(tmp_path):
    (tmp_path / "add_numbers.py").write_text(FUNCTION_TOOL)
    registry = ToolRegistry()

    assert await ToolLoader(registry).load_directory(str(tmp_path)) == ["add-numbers"]

    tool = registry.get("add-numbers")
    assert tool.description == "adds"
    assert tool.parameters == {"type": "object", "properties": {}}
    ok = await tool.execute("c1", {"a": 1, "b": 2})
    assert ok.content[0].text == "3" and not ok.is_error
    assert (await tool.execute("c1", {})).is_error


async def test_load_directory_reads_yaml_metadata_with_handler(tmp_path):
    (tmp_path / "greet_mod.yaml").write_text("name: greet\ndescription: says hi\nexecution_mode: sequential\n")
    (tmp_path / "greet_mod.py").write_text("async def execute(tool_call_id, params):\n    return 'hi'\n")
    registry = ToolRegistry()

    assert await ToolLoader(registry).load_directory(str(tmp_path)) == ["greet"]

    tool = registry.get("greet")
    assert tool.execution_mode == "sequential"
    assert (await tool.execute("c1", {})).content[0].text == "hi"


async def test_load_directory_logs_broken_file_and_skips_it(tmp_path, capsys):
    (tmp_path / "broken_tool_mod.py").write_text("raise RuntimeError('nope')\n")

    assert await ToolLoader(ToolRegistry()).load_directory(str(tmp_path)) == []
    assert "[ToolLoader] Failed to load broken_tool_mod.py: nope" in capsys.readouterr().out
