"""SupervisorTopology — 1:N 단일 조율자 패턴.

오케스트레이터(LLM)가 tool_call로 어떤 노드를 호출할지 결정.
Base 구현으로 충분하므로 별도 오버라이드 없음.
"""

from __future__ import annotations

from .base import BaseTopology


class SupervisorTopology(BaseTopology):
    """모든 노드가 오케스트레이터에게 평등하게 보이는 flat 구조."""

    pass
