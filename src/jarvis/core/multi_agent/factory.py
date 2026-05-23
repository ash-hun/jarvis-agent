"""AgentFactory — 설정 기반 AgentNode 인스턴스 생성.

AgentDefinition으로 노드를 선언하면 factory가 격리된 AgentSession을 생성해
AgentNode로 래핑한다. get_or_create()는 멱등 — 동일 name 재요청 시 캐시 반환.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentDefinition:
    """단일 에이전트 노드 선언."""

    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)  # 허용할 builtin tool 이름
    model_override: str | None = None               # None이면 부모 설정 상속


class AgentFactory:
    """AgentDefinition → AgentNode 생성 + 수명 관리."""

    def __init__(self, event_sink: object = None) -> None:
        self._nodes: dict[str, AgentNode] = {}  # noqa: F821
        self._event_sink = event_sink  # sub-agent 이벤트를 부모로 포워딩할 sink

    def create(self, definition: AgentDefinition, base_session: object) -> AgentNode:  # noqa: F821
        """base_session을 복제해 격리된 AgentNode를 반환.

        현재 구현은 base_session 자체를 공유한다.
        실제 격리가 필요하면 startup._build_infra()를 호출해 독립 인프라를 구성한다.
        """
        from .node import AgentNode

        node = AgentNode(
            name=definition.name,
            session=base_session,
            capabilities=definition.capabilities,
            event_sink=self._event_sink,  # type: ignore[arg-type]
        )
        return node

    def get_or_create(
        self,
        definition: AgentDefinition,
        base_session: object,
    ) -> AgentNode:  # noqa: F821
        """멱등 — 동일 name이 이미 있으면 캐시 반환."""
        if definition.name not in self._nodes:
            self._nodes[definition.name] = self.create(definition, base_session)
        return self._nodes[definition.name]

    def release(self, name: str) -> None:
        """노드 캐시에서 제거."""
        self._nodes.pop(name, None)

    def __len__(self) -> int:
        return len(self._nodes)
