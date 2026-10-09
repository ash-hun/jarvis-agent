"""평가 사례(jsonl 한 줄)의 형식."""

import json
from pathlib import Path
from typing import Literal

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
    """저장소에 미리 넣어 둘 항목 하나. remember(기억) 또는 skill(절차) 중 하나."""

    remember: str | None = None
    kind: MemoryKind = MemoryKind.SEMANTIC
    visibility: Visibility = "private"
    scope: ScopeSpec | None = None  # 없으면 사례의 scope 를 쓴다
    at: str | None = None  # ISO 날짜. 지식 갱신처럼 순서가 중요한 사례용
    importance: float | None = None
    rehearsal_count: int = 0  # 되뇌기 횟수. 감쇠 저항 검증용
    skill: str | None = None  # 절차 기억: 스킬 이름
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


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
    probe_kind: Literal["recall", "procedures"] = "recall"  # procedures 면 스킬 이름 목록을 결과로 본다
    expect: Expect

    def step_scope(self, step: SetupStep) -> MemoryScope:
        return (step.scope or self.scope).to_scope()


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


# ── 작업 기억 스위트 ────────────────────────────────────────────────────────────
# 저장소가 아니라 턴 단위 변환(observe)을 잰다. 사례는 턴마다 몇 개의 메시지를 몇 글자로 더할지로 정의한다.


class WorkingTurn(BaseModel):
    messages: int  # 이번 턴에 이력에 더할 메시지 수 (user, assistant 번갈아)
    chars: int = 100


class WorkingConfig(BaseModel):
    threshold_chars: int = 80_000
    keep_recent: int = 10
    window_size: int = 50
    rebuild_between_turns: bool = False  # True 면 턴마다 매니저를 새로 만든다(저장소는 공유). 영속성 검증용


class WorkingExpect(BaseModel):
    summarizer_calls: list[int]  # 턴별 요약기 호출 수
    max_messages: int | None = None  # 어느 턴이든 컨텍스트 메시지 수 상한(요약 메시지 포함)
    # 이 턴(0부터)부터 요약 메시지가 앞에 붙어야 한다. None 이면 끝까지 없어야 한다
    summary_from_turn: int | None = None
    first_role: str | None = None  # 마지막 턴 컨텍스트에서 요약 다음 첫 메시지의 role


class WorkingCase(BaseModel):
    suite: str
    case: str
    config: WorkingConfig = Field(default_factory=WorkingConfig)
    turns: list[WorkingTurn]
    expect: WorkingExpect


def load_working_cases(path: Path) -> list[WorkingCase]:
    cases: list[WorkingCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(WorkingCase.model_validate(json.loads(line)))
    return cases
