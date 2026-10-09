"""절차 기억. "어떻게 하는지"는 스킬 파일이 정본이라 저장소에 복제하지 않고 읽기 전용으로 노출한다."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from jarvis.memory.stores.protocol import tokens_of


@dataclass(frozen=True)
class Procedure:
    name: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, query: str) -> bool:
        """질의 토큰에 이름이나 별칭이 그대로 들어 있을 때만. 부분 일치는 오탐이 많다."""
        tokens = set(tokens_of(query))
        names = {self.name.lower(), *(a.lower() for a in self.aliases)}
        return bool(tokens & names)


@runtime_checkable
class ProceduralSource(Protocol):
    def match(self, query: str) -> list[Procedure]: ...


class InMemoryProcedures:
    def __init__(self, procedures: list[Procedure] | None = None) -> None:
        self._procedures = list(procedures or [])

    def add(self, procedure: Procedure) -> None:
        self._procedures.append(procedure)

    def match(self, query: str) -> list[Procedure]:
        return [p for p in self._procedures if p.matches(query)]


class SkillRegistryProcedures:
    """SkillRegistry 를 절차 기억으로 본다. 스킬이 바뀌면 바로 반영된다(복제 없음)."""

    def __init__(self, registry: object) -> None:
        self._registry = registry

    def match(self, query: str) -> list[Procedure]:
        skills = getattr(self._registry, "list_all", lambda: [])()
        procedures = [
            Procedure(name=s.name, description=s.description or "", aliases=tuple(getattr(s, "aliases", ()) or ()))
            for s in skills
        ]
        return [p for p in procedures if p.matches(query)]
