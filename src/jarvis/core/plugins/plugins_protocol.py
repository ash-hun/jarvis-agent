"""[core] 플러그인 훅의 기반 클래스(JarvisPlugin)와 훅 결과 타입(HookResult)을 정한다."""

from typing import Any, TypedDict

from jarvis.core.policy.pipeline import AuthContext
from jarvis.model_layer.model_types import Message


class HookResult(TypedDict, total=False):
    modified_messages: list[Message]
    block: bool
    reason: str
    modified_content: list[dict[str, Any]]


class JarvisPlugin:
    """플러그인의 기반. 각 훅은 선택이다. 오버라이드하지 않은 훅은 no-op(None 반환).

    Pi: Extension Protocol 동일 패턴. 모든 구현은 멱등성(idempotent)을 보장해야 함.
    """

    name: str
    version: str

    async def before_agent_start(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> HookResult | None:
        return None

    async def before_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        auth: AuthContext,
    ) -> HookResult | None:
        return None

    async def after_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResult | None:
        return None

    async def on_message_end(
        self,
        message: Message,
    ) -> Message | None:
        return None

    async def transform_context(
        self,
        messages: list[Message],
    ) -> list[Message] | None:
        return None
