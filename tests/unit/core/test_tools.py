"""core/tools/ — ToolRegistry + 내장 툴 테스트."""
import pytest

from jarvis.model_layer.types import TextContent, ToolResultMessage
from jarvis.core.tools.registry import ToolRegistry

# ── ToolRegistry 기본 동작 ─────────────────────────────────────────────────────

class MockTool:
    name = "mock-tool"
    description = "A mock tool for testing"
    parameters = {"type": "object", "properties": {}}
    execution_mode = "parallel"

    async def execute(self, tool_call_id, params, signal=None):
        return ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            content=[TextContent(text=f"executed with {params}")],
        )


class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        registry.register(MockTool())
        tool = registry.get("mock-tool")
        assert tool is not None
        assert tool.name == "mock-tool"

    def test_first_registration_wins(self):
        registry = ToolRegistry()

        class Tool1:
            name = "dup-tool"
            description = "first"
            parameters = {}
            execution_mode = "parallel"
            async def execute(self, *a, **k): ...

        class Tool2:
            name = "dup-tool"
            description = "second"
            parameters = {}
            execution_mode = "parallel"
            async def execute(self, *a, **k): ...

        registry.register(Tool1())
        registry.register(Tool2())
        assert registry.get("dup-tool").description == "first"

    def test_register_force_overwrites(self):
        registry = ToolRegistry()

        class T1:
            name, description, parameters, execution_mode = "t", "v1", {}, "parallel"
            async def execute(self, *a, **k): ...

        class T2:
            name, description, parameters, execution_mode = "t", "v2", {}, "parallel"
            async def execute(self, *a, **k): ...

        registry.register(T1())
        registry.register_force(T2())
        assert registry.get("t").description == "v2"

    def test_unregister(self):
        registry = ToolRegistry()
        registry.register(MockTool())
        registry.unregister("mock-tool")
        assert registry.get("mock-tool") is None

    def test_list_all(self):
        registry = ToolRegistry()
        registry.register(MockTool())
        assert len(registry.list_all()) == 1

    def test_to_llm_tools(self):
        registry = ToolRegistry()
        registry.register(MockTool())
        tools = registry.to_llm_tools()
        assert len(tools) == 1
        assert tools[0].name == "mock-tool"

    async def test_execute_existing_tool(self):
        registry = ToolRegistry()
        registry.register(MockTool())
        result = await registry.execute("call_01", "mock-tool", {"key": "val"})
        assert result.is_error is False
        assert "executed" in result.content[0].text

    async def test_execute_nonexistent_tool(self):
        registry = ToolRegistry()
        result = await registry.execute("call_01", "ghost-tool", {})
        assert result.is_error is True
        assert "not found" in result.content[0].text


# ── BashTool 테스트 ───────────────────────────────────────────────────────────

class TestBashTool:
    @pytest.fixture
    def bash_tool(self):
        from jarvis.core.tools.builtin.bash import BashTool
        return BashTool()

    async def test_simple_command(self, bash_tool):
        result = await bash_tool.execute("c1", {"command": "echo hello"})
        assert result.is_error is False
        assert "hello" in result.content[0].text

    async def test_failed_command(self, bash_tool):
        result = await bash_tool.execute("c1", {"command": "exit 1"})
        assert result.is_error is True

    async def test_timeout(self, bash_tool):
        result = await bash_tool.execute("c1", {"command": "sleep 10", "timeout": 1})
        assert result.is_error is True
        assert "timed out" in result.content[0].text


# ── ReadFileTool 테스트 ───────────────────────────────────────────────────────

class TestReadFileTool:
    @pytest.fixture
    def read_tool(self):
        from jarvis.core.tools.builtin.read_file import ReadFileTool
        return ReadFileTool()

    async def test_read_existing_file(self, read_tool, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = await read_tool.execute("c1", {"path": str(f)})
        assert result.is_error is False
        assert "line1" in result.content[0].text

    async def test_read_nonexistent_file(self, read_tool):
        result = await read_tool.execute("c1", {"path": "/nonexistent/path.txt"})
        assert result.is_error is True
        assert "not found" in result.content[0].text

    async def test_read_with_limit(self, read_tool, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line {i}" for i in range(100)))
        result = await read_tool.execute("c1", {"path": str(f), "limit": 5})
        assert result.is_error is False
        lines = result.content[0].text.strip().split("\n")
        assert len(lines) == 5


# ── WriteFileTool 테스트 ──────────────────────────────────────────────────────

class TestWriteFileTool:
    @pytest.fixture
    def write_tool(self):
        from jarvis.core.tools.builtin.write_file import WriteFileTool
        return WriteFileTool()

    async def test_write_new_file(self, write_tool, tmp_path):
        f = tmp_path / "out.txt"
        result = await write_tool.execute("c1", {"path": str(f), "content": "hello"})
        assert result.is_error is False
        assert f.read_text() == "hello"

    async def test_overwrite_existing_file(self, write_tool, tmp_path):
        f = tmp_path / "out.txt"
        f.write_text("old content")
        result = await write_tool.execute("c1", {"path": str(f), "content": "new content"})
        assert result.is_error is False
        assert f.read_text() == "new content"

    async def test_creates_parent_directories(self, write_tool, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        result = await write_tool.execute("c1", {"path": str(f), "content": "deep"})
        assert result.is_error is False
        assert f.exists()

    async def test_reports_bytes_written(self, write_tool, tmp_path):
        f = tmp_path / "out.txt"
        result = await write_tool.execute("c1", {"path": str(f), "content": "abc"})
        assert "3" in result.content[0].text


# ── EditFileTool 테스트 ───────────────────────────────────────────────────────

class TestEditFileTool:
    @pytest.fixture
    def edit_tool(self):
        from jarvis.core.tools.builtin.edit_file import EditFileTool
        return EditFileTool()

    async def test_replace_single_occurrence(self, edit_tool, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def foo():\n    pass\n")
        result = await edit_tool.execute("c1", {"path": str(f), "old_string": "pass", "new_string": "return 42"})
        assert result.is_error is False
        assert "return 42" in f.read_text()

    async def test_old_string_not_found(self, edit_tool, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def foo(): pass\n")
        result = await edit_tool.execute("c1", {"path": str(f), "old_string": "MISSING", "new_string": "x"})
        assert result.is_error is True
        assert "not found" in result.content[0].text

    async def test_ambiguous_without_replace_all(self, edit_tool, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\nx = 1\n")
        result = await edit_tool.execute("c1", {"path": str(f), "old_string": "x = 1", "new_string": "y = 2"})
        assert result.is_error is True
        assert "replace_all" in result.content[0].text

    async def test_replace_all(self, edit_tool, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\nx = 1\n")
        result = await edit_tool.execute(
            "c1", {"path": str(f), "old_string": "x = 1", "new_string": "y = 2", "replace_all": True}
        )
        assert result.is_error is False
        assert f.read_text() == "y = 2\ny = 2\n"

    async def test_file_not_found(self, edit_tool):
        result = await edit_tool.execute("c1", {"path": "/nonexistent.py", "old_string": "x", "new_string": "y"})
        assert result.is_error is True
        assert "not found" in result.content[0].text


class _Named:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters, self.execution_mode = name, name, {}, "parallel"

    async def execute(self, tool_call_id, params, signal=None):
        raise AssertionError("실행하지 않는다")


def test_picked_registry_sees_tools_registered_after_it_was_made():
    from jarvis.core.tools.registry import PickedToolRegistry, ToolRegistry

    app, opt_in = ToolRegistry(), ToolRegistry()
    app.register(_Named("lh_notice"))
    app.register(_Named("bash"))
    opt_in.register(_Named("ask_agent"))
    picked = PickedToolRegistry((app, opt_in), ("lh_notice", "ask_agent"), prefixes=("procedure_",))
    assert [t.name for t in picked.list_all()] == ["lh_notice", "ask_agent"]

    app.register(_Named("procedure_weekly-report"))  # 세션을 만든 뒤 승인된 절차
    picked.register(_Named("focus_note"))  # 세션이 직접 더한 도구
    names = [t.name for t in picked.to_llm_tools()]
    assert names == ["lh_notice", "ask_agent", "procedure_weekly-report", "focus_note"]
    assert picked.get("bash") is None  # 정의에 없는 도구는 계속 안 보인다
    app.unregister("procedure_weekly-report")
    assert picked.get("procedure_weekly-report") is None
