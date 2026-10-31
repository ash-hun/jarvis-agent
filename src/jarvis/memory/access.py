"""[memory] 에이전트별 층 읽기 정책과, 그 정책으로 읽을 수 있는 소유 에이전트를 계산하는 순수 함수."""

from dataclasses import dataclass
from collections.abc import Mapping
from pydantic import BaseModel, ConfigDict, Field

from jarvis.memory.types import MemoryKind

SELF = "self"


class MemoryReadPolicy(BaseModel):
    """층마다 더 읽을 수 있는 소유 에이전트. 자기 것은 적지 않아도 늘 읽는다. self 는 읽는 에이전트 자신이다."""

    model_config = ConfigDict(extra="forbid")

    edm: list[str] = Field(default_factory=lambda: [SELF])  # 다른 에이전트의 대화는 기본 거부
    pdm: list[str] = Field(default_factory=lambda: [SELF])  # 절차 공유는 적은 에이전트만


class MemoryPolicy(BaseModel):
    """team/<id>.yaml 의 memory 블록. 사용자 프로필(의미 기억)은 정책 밖이고 같은 사용자의 모든 에이전트가 읽는다."""

    model_config = ConfigDict(extra="forbid")

    read: MemoryReadPolicy = Field(default_factory=MemoryReadPolicy)


DEFAULT_POLICY = MemoryPolicy()


@dataclass(frozen=True)
class Readable:
    """한 에이전트가 층별로 읽을 수 있는 소유 에이전트. 저장소는 이 값으로만 거른다."""

    edm: frozenset[str]
    pdm: frozenset[str]

    @classmethod
    def own(cls, agent_id: str) -> "Readable":
        return cls(edm=frozenset({agent_id}), pdm=frozenset({agent_id}))

    def allows(self, owner: str, kind: MemoryKind) -> bool:
        owners = readable_owners(self, kind)
        return owners is None or owner in owners


def readable_owners(readable: Readable, kind: MemoryKind) -> frozenset[str] | None:
    """None 은 소유 에이전트를 가리지 않는다는 뜻이다(사용자 프로필)."""
    if kind is MemoryKind.EPISODIC:
        return readable.edm
    if kind is MemoryKind.PROCEDURAL:
        return readable.pdm
    return None


def resolve(policies: Mapping[str, MemoryPolicy], reader: str) -> Readable:
    """정책에 없는 에이전트(main, 서브 에이전트)는 기본 정책, 즉 자기 것만 읽는다."""
    read = policies.get(reader, DEFAULT_POLICY).read

    def owners(names: list[str]) -> frozenset[str]:
        return frozenset({reader, *(reader if n == SELF else n for n in names)})

    return Readable(edm=owners(read.edm), pdm=owners(read.pdm))
