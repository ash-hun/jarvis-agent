"""[core] 모든 노드가 감독자(LLM)에게 평등하게 보이는 1:N flat 토폴로지."""

from .topology_base import BaseTopology


class SupervisorTopology(BaseTopology):
    """모든 노드가 오케스트레이터에게 평등하게 보이는 flat 구조."""

    pass
