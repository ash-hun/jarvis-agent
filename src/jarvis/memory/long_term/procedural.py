"""[memory] "어떻게 하는지"는 스킬 파일이 정본이라 절차 기억을 저장소에 복제하지 않고 읽기 전용으로 노출한다."""

from typing import Any
from dataclasses import dataclass, field

from jarvis.memory.stores.store_protocol import tokens_of


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


class ProceduralSource:
    """절차 기억의 출처. 후보 목록(candidates)만 하위 클래스가 정하고 질의 매칭은 공유한다. 기본은 아는 절차가 없다."""

    def candidates(self) -> list[Procedure]:
        return []

    def match(self, query: str) -> list[Procedure]:
        return [p for p in self.candidates() if p.matches(query)]


class InMemoryProcedures(ProceduralSource):
    def __init__(self, procedures: list[Procedure] | None = None) -> None:
        self._procedures = list(procedures or [])

    def add(self, procedure: Procedure) -> None:
        self._procedures.append(procedure)

    def candidates(self) -> list[Procedure]:
        return self._procedures


class SkillRegistryProcedures(ProceduralSource):
    """SkillRegistry 를 절차 기억으로 본다. 스킬이 바뀌면 바로 반영된다(복제 없음)."""

    def __init__(self, registry: object) -> None:
        self._registry = registry

    def candidates(self) -> list[Procedure]:
        # registry 를 object 로 받으므로 스킬 항목도 덕 타이핑으로 읽는다
        skills: list[Any] = getattr(self._registry, "list_all", lambda: [])()
        return [
            Procedure(name=s.name, description=s.description or "", aliases=tuple(getattr(s, "aliases", ()) or ()))
            for s in skills
        ]
