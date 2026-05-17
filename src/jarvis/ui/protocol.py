from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.agent_layer.types import AgentEvent


@runtime_checkable
class UIAdapter(Protocol):
    """
    UI 레이어 Protocol — core layer가 ui를 역방향으로 의존하지 않도록 분리.
    TUI와 WebUI 모두 이 Protocol을 구현.
    """

    async def on_agent_event(self, event: AgentEvent) -> None: ...

    async def on_stream_text(self, delta: str) -> None: ...

    async def request_approval(self, command: str, reason: str) -> bool: ...

    async def show_error(self, error: str) -> None: ...
