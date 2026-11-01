"""tools 기능: GET /api/tools 가 승인 필요 여부를 표시하고, watch_files 가 켜져 있으면 새 도구 파일을 바로 싣는다."""

import pytest
import asyncio

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402


def test_tools_list_marks_approval_required(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path)) as client:
        tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}

    assert tools["bash"]["approval"] is True
    assert tools["read_file"]["approval"] is False


async def test_watch_files_loads_a_tool_written_after_start(monkeypatch, tmp_path):
    from jarvis.core.skills.skills_registry import SkillRegistry
    from jarvis.core.tools.tools_registry import ToolRegistry
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.app.infra_builder import InfraBuilder
    from jarvis.jarvis_config import JarvisSettings

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    monkeypatch.setenv("JARVIS_PLUGIN__TOOLS_DIR", str(tools_dir))
    monkeypatch.setenv("JARVIS_PLUGIN__SKILLS_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("JARVIS_PLUGIN__PLUGINS_DIR", str(tmp_path / "none"))
    registry = ToolRegistry()
    watcher = InfraBuilder(JarvisSettings()).build_extension_watcher(registry, SkillRegistry(), PluginRunner())
    assert watcher is not None and watcher.directories == [str(tools_dir.resolve())]

    await watcher.start()
    try:
        await asyncio.sleep(0.3)
        (tools_dir / "hello.py").write_text(
            "TOOL_NAME = 'hello'\n\nasync def execute(tool_call_id, params):\n    return 'hi'\n"
        )
        for _ in range(100):
            if registry.get("hello") is not None:
                break
            await asyncio.sleep(0.05)
    finally:
        await watcher.stop()

    assert registry.get("hello") is not None


def test_watch_files_off_builds_no_watcher(monkeypatch, tmp_path):
    from jarvis.core.skills.skills_registry import SkillRegistry
    from jarvis.core.tools.tools_registry import ToolRegistry
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.app.infra_builder import InfraBuilder
    from jarvis.jarvis_config import JarvisSettings

    (tmp_path / "tools").mkdir()
    monkeypatch.setenv("JARVIS_PLUGIN__TOOLS_DIR", str(tmp_path / "tools"))
    monkeypatch.setenv("JARVIS_PLUGIN__WATCH_FILES", "false")

    builder = InfraBuilder(JarvisSettings())

    assert builder.build_extension_watcher(ToolRegistry(), SkillRegistry(), PluginRunner()) is None
