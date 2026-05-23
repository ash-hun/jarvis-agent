"""BlackboardTopology — 공유 블랙보드 기반 토폴로지.

모든 노드가 SharedBlackboard를 통해 간접 통신.
토폴로지 자체는 Base와 동일; 블랙보드 연동은 BlackboardOrchestrator가 담당.
"""

from __future__ import annotations

from .base import BaseTopology


class BlackboardTopology(BaseTopology):
    """Shared workspace 기반. 노드 간 직접 연결 없음."""

    pass
