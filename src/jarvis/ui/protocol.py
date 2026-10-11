"""[ui] UIAdapter: 화면(TUI, Web)이 에이전트 이벤트, 스트림, 승인, 오류를 받는 기본 어댑터."""

from __future__ import annotations

from jarvis.agent_layer.types import AgentEvent


class UIAdapter:
    """화면 구현(JarvisTUI, PerConnectionAdapter)의 부모. 기본은 받은 것을 버리고 승인은 거절한다."""

    async def on_agent_event(self, event: AgentEvent) -> None:
        return None

    async def on_stream_text(self, delta: str) -> None:
        return None

    async def request_approval(self, command: str, reason: str, always_pattern: str = "") -> bool | str:
        # 승인 화면이 없는 어댑터는 실행을 막는 쪽이 안전하다
        return False

    async def show_error(self, error: str) -> None:
        return None
