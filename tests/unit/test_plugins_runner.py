"""plugins 의 PluginRunner: 첫 차단에서 멈추고, 실패를 격리하고, 이름으로 뺄 수 있는지 검증한다."""

from jarvis.model_layer.model_types import TextContent, UserMessage
from jarvis.core.plugins.plugins_protocol import JarvisPlugin
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.policy.pipeline import AuthContext

AUTH = AuthContext(user_id="u", roles=frozenset({"user"}))


class Blocker(JarvisPlugin):
    name = "blocker"
    version = "1"

    async def before_tool_call(self, tool_name, args, auth):  # type: ignore[no-untyped-def]
        return {"block": True, "reason": f"no {tool_name}"}


class Broken(JarvisPlugin):
    name = "broken"
    version = "1"

    async def transform_context(self, messages):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class Appender(JarvisPlugin):
    name = "appender"
    version = "1"

    async def transform_context(self, messages):  # type: ignore[no-untyped-def]
        return [*messages, UserMessage(content=[TextContent(text="added")])]


class Quiet(JarvisPlugin):
    name = "quiet"
    version = "1"


async def test_before_tool_call_returns_first_block():
    runner = PluginRunner([JarvisPlugin(), Blocker()])

    assert await runner.emit_before_tool_call("bash", {}, AUTH) == {"block": True, "reason": "no bash"}


async def test_before_tool_call_default_plugin_does_not_block():
    assert await PluginRunner([Quiet()]).emit_before_tool_call("bash", {}, AUTH) is None


async def test_failure_is_isolated_and_logged(capsys):
    msg = UserMessage(content=[TextContent(text="hi")])

    out = await PluginRunner([Broken(), Appender()]).emit_transform_context([msg])

    assert len(out) == 2
    assert "[PluginRunner] Plugin 'broken' failed in 'transform_context': boom" in capsys.readouterr().out


async def test_unregister_by_name_twice_removes_the_plugin():
    runner = PluginRunner()
    runner.register(Blocker())

    runner.unregister("blocker")
    runner.unregister("blocker")

    assert await runner.emit_before_tool_call("bash", {}, AUTH) is None
