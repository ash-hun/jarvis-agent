"""[core] 노드 간 직접 연결 없이 공유 블랙보드(연동은 BlackboardOrchestrator 담당)로만 통신하는 토폴로지."""

from .base import BaseTopology


class BlackboardTopology(BaseTopology):
    """Shared workspace 기반. 노드 간 직접 연결 없음."""

    pass
