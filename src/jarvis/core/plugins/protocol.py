from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable

from jarvis.core.policy.pipeline import AuthContext
from jarvis.model_layer.types import Message


class HookResult(TypedDict, total=False):
    modified_messages: list[Message]
    block: bool
    reason: str
    modified_content: list[dict[str, Any]]


@runtime_checkable
class JarvisPlugin(Protocol):
    """
    플러그인 Protocol. 각 훅은 Optional — 구현 안 하면 no-op.
    Pi: Extension Protocol 동일 패턴.
    모든 구현은 멱등성(idempotent)을 보장해야 함.
    """
    name: str
    version: str

    async def before_agent_start(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> HookResult | None: ...

    async def before_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        auth: AuthContext,
    ) -> HookResult | None: ...

    async def after_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResult | None: ...

    async def on_message_end(
        self,
        message: Message,
    ) -> Message | None: ...

    async def transform_context(
        self,
        messages: list[Message],
    ) -> list[Message] | None: ...
