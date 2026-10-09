"""Multi-Agent 오케스트레이션 패키지.

사용 예:
    from jarvis.core.multi_agent import (
        AgentTask, AgentResult,
        AgentNode, AgentNodeTool,
        SupervisorTopology, HierarchicalTopology, P2PTopology, BlackboardTopology,
        SupervisorOrchestrator, HierarchicalOrchestrator,
        MarketOrchestrator, BlackboardOrchestrator,
        OrchestratorPipeline,
        SharedBlackboard,
        AgentFactory, AgentDefinition,
    )
"""

from .blackboard import SharedBlackboard
from .factory import AgentDefinition, AgentFactory, AgentMemoryPolicy
from .loader import load_agent_definitions
from .node import AgentNode, LazyAgentNode
from .orchestrators import (
    Bid,
    BlackboardOrchestrator,
    HierarchicalOrchestrator,
    MarketOrchestrator,
    OrchestratorPipeline,
    SupervisorOrchestrator,
)
from .protocol import AgentNodeProtocol, OrchestratorProtocol, TopologyProtocol
from .task import AgentResult, AgentTask
from .tool import AgentNodeTool
from .topologies import (
    BlackboardTopology,
    HierarchicalTopology,
    P2PTopology,
    SupervisorTopology,
)

__all__ = [
    # 타입
    "AgentTask",
    "AgentResult",
    # 프로토콜
    "AgentNodeProtocol",
    "TopologyProtocol",
    "OrchestratorProtocol",
    # 노드
    "AgentNode",
    "LazyAgentNode",
    "AgentNodeTool",
    # 블랙보드
    "SharedBlackboard",
    # 토폴로지
    "SupervisorTopology",
    "HierarchicalTopology",
    "P2PTopology",
    "BlackboardTopology",
    # 오케스트레이터
    "SupervisorOrchestrator",
    "HierarchicalOrchestrator",
    "MarketOrchestrator",
    "Bid",
    "BlackboardOrchestrator",
    "OrchestratorPipeline",
    # 팩토리 + 로더
    "AgentFactory",
    "AgentDefinition",
    "AgentMemoryPolicy",
    "load_agent_definitions",
]
