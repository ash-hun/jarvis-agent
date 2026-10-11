"""JarvisPlugin 기반 클래스, PluginRunner, PluginLoader 테스트."""

from jarvis.core.plugins.loader import PluginLoader
from jarvis.core.plugins.protocol import JarvisPlugin
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.policy.pipeline import AuthContext
from jarvis.model_layer.types import TextContent, UserMessage

AUTH = AuthContext(user_id="u", roles=frozenset({"user"}))


class Blocker(JarvisPlugin):
    name = "blocker"
    version = "1"

    async def before_tool_call(self, tool_name, args, auth):
        return {"block": True, "reason": f"no {tool_name}"}


class Broken(JarvisPlugin):
    name = "broken"
    version = "1"

    async def transform_context(self, messages):
        raise RuntimeError("boom")


class Appender(JarvisPlugin):
    name = "appender"
    version = "1"

    async def transform_context(self, messages):
        return [*messages, UserMessage(content=[TextContent(text="added")])]


class TestJarvisPluginDefaults:
    async def test_all_hooks_are_noop(self):
        plugin = JarvisPlugin()
        msg = UserMessage(content=[TextContent(text="hi")])
        assert await plugin.before_agent_start("p", {}) is None
        assert await plugin.before_tool_call("bash", {}, AUTH) is None
        assert await plugin.after_tool_call("bash", {}, {}) is None
        assert await plugin.on_message_end(msg) is None
        assert await plugin.transform_context([msg]) is None


class TestPluginRunner:
    async def test_block_short_circuits(self):
        runner = PluginRunner([JarvisPlugin(), Blocker()])
        result = await runner.emit_before_tool_call("bash", {}, AUTH)
        assert result == {"block": True, "reason": "no bash"}

    async def test_default_plugin_does_not_block(self):
        class Quiet(JarvisPlugin):
            name = "quiet"
            version = "1"

        assert await PluginRunner([Quiet()]).emit_before_tool_call("bash", {}, AUTH) is None

    async def test_failure_is_isolated_and_logged(self, capsys):
        msg = UserMessage(content=[TextContent(text="hi")])
        runner = PluginRunner([Broken(), Appender()])
        out = await runner.emit_transform_context([msg])
        assert len(out) == 2
        assert "[PluginRunner] Plugin 'broken' failed in 'transform_context': boom" in capsys.readouterr().out

    def test_unregister_by_name(self):
        runner = PluginRunner()
        runner.register(Blocker())
        runner.unregister("blocker")
        runner.unregister("blocker")
        assert runner._plugins == []


class TestPluginLoader:
    async def test_missing_directory_loads_nothing(self, tmp_path):
        assert await PluginLoader(PluginRunner()).load_directory(str(tmp_path / "nope")) == []

    async def test_loads_duck_typed_and_subclass_plugins(self, tmp_path):
        (tmp_path / "duck.py").write_text(
            "class Duck:\n    name = 'duck'\n    version = '0.1'\n"
        )
        (tmp_path / "sub.py").write_text(
            "from jarvis.core.plugins.protocol import JarvisPlugin\n\n"
            "class Sub(JarvisPlugin):\n    name = 'sub'\n    version = '0.1'\n"
        )
        runner = PluginRunner()
        loaded = await PluginLoader(runner).load_directory(str(tmp_path))
        assert sorted(loaded) == ["duck", "sub"]

    async def test_broken_file_is_logged(self, tmp_path, capsys):
        (tmp_path / "bad.py").write_text("raise RuntimeError('nope')\n")
        loaded = await PluginLoader(PluginRunner()).load_directory(str(tmp_path))
        assert loaded == []
        assert "[PluginLoader] Failed to load bad.py: nope" in capsys.readouterr().out
