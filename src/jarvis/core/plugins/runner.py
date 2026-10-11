"""[core] 등록된 플러그인의 훅을 오류 격리와 체인 적용으로 실행한다."""

from __future__ import annotations

from typing import Any

from jarvis.common.logger import get_logger
from jarvis.core.plugins.protocol import HookResult, JarvisPlugin
from jarvis.model_layer.types import Message

logger = get_logger(__name__)


class PluginRunner:
    """플러그인 훅 실행기. Pi: ExtensionRunner 패턴.

    - 한 플러그인 실패가 전체를 멈추지 않음 (error isolation)
    - transform 훅은 체인으로 순차 적용
    """

    def __init__(self, plugins: list[JarvisPlugin] | None = None) -> None:
        self._plugins: list[JarvisPlugin] = plugins or []

    def register(self, plugin: JarvisPlugin) -> None:
        self._plugins.append(plugin)

    def unregister(self, name: str) -> None:
        self._plugins = [p for p in self._plugins if p.name != name]

    async def emit_before_agent_start(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> None:
        for plugin in self._plugins:
            try:
                await plugin.before_agent_start(prompt, context)
            except Exception as exc:
                _log_error(plugin.name, "before_agent_start", exc)

    async def emit_before_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        auth: Any,  # AuthContext 가 보통이지만 호출부가 None 이나 다른 인증 객체를 넘길 수 있다
    ) -> HookResult | None:
        for plugin in self._plugins:
            try:
                result = await plugin.before_tool_call(tool_name, args, auth)
                if result and result.get("block"):
                    return result
            except Exception as exc:
                _log_error(plugin.name, "before_tool_call", exc)
        return None

    async def emit_after_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResult | None:
        for plugin in self._plugins:
            try:
                hook_result = await plugin.after_tool_call(tool_name, args, result)
                if hook_result:
                    return hook_result
            except Exception as exc:
                _log_error(plugin.name, "after_tool_call", exc)
        return None

    async def emit_on_message_end(self, message: Message) -> Message:
        for plugin in self._plugins:
            try:
                modified = await plugin.on_message_end(message)
                if modified is not None:
                    message = modified
            except Exception as exc:
                _log_error(plugin.name, "on_message_end", exc)
        return message

    async def emit_transform_context(self, messages: list[Message]) -> list[Message]:
        for plugin in self._plugins:
            try:
                modified = await plugin.transform_context(messages)
                if modified is not None:
                    messages = modified
            except Exception as exc:
                _log_error(plugin.name, "transform_context", exc)
        return messages


def _log_error(plugin_name: str, hook: str, exc: Exception) -> None:
    logger.info(f"[PluginRunner] Plugin '{plugin_name}' failed in '{hook}': {exc}")
