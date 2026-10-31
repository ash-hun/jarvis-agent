"""plugins 의 JarvisPlugin 기본 클래스: 모든 훅의 기본 동작이 아무것도 바꾸지 않는지 검증한다."""

from jarvis.model_layer.model_types import TextContent, UserMessage
from jarvis.core.plugins.plugins_protocol import JarvisPlugin
from jarvis.core.policy.pipeline import AuthContext


async def test_all_hooks_are_noop():
    plugin = JarvisPlugin()
    msg = UserMessage(content=[TextContent(text="hi")])
    auth = AuthContext(user_id="u", roles=frozenset({"user"}))

    assert await plugin.before_agent_start("p", {}) is None
    assert await plugin.before_tool_call("bash", {}, auth) is None
    assert await plugin.after_tool_call("bash", {}, {}) is None
    assert await plugin.on_message_end(msg) is None
    assert await plugin.transform_context([msg]) is None
