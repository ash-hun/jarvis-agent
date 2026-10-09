"""평가 사례(jsonl 한 줄)의 형식."""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.memory.scope import MAIN_AGENT, MemoryScope
from jarvis.memory.types import MemoryKind, Visibility


class ScopeSpec(BaseModel):
    user_id: str
    agent_id: str = MAIN_AGENT
    session_id: str | None = None

    def to_scope(self) -> MemoryScope:
        return MemoryScope(user_id=self.user_id, agent_id=self.agent_id, session_id=self.session_id)


class SetupStep(BaseModel):
    """저장소에 미리 넣어 둘 항목 하나."""

    remember: str
    kind: MemoryKind = MemoryKind.SEMANTIC
    visibility: Visibility = "private"
    scope: ScopeSpec | None = None  # 없으면 사례의 scope 를 쓴다
    at: str | None = None  # ISO 날짜. 지식 갱신처럼 순서가 중요한 사례용


class Expect(BaseModel):
    contains: list[str] = Field(default_factory=list)  # 상위 top_k 안에 전부 있어야 한다
    not_contains: list[str] = Field(default_factory=list)  # 하나라도 나오면 누수
    empty: bool = False  # 아무것도 나오지 않아야 한다(기권)
    top_k: int = 3


class EvalCase(BaseModel):
    suite: str
    case: str
    setup: list[SetupStep]
    scope: ScopeSpec
    probe: str
    expect: Expect

    def step_scope(self, step: SetupStep) -> MemoryScope:
        return (step.scope or self.scope).to_scope()


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return cases
