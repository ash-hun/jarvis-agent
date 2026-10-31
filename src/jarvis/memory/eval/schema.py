"""[memory] 평가 사례(jsonl 한 줄)의 형식과 로더."""

import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

from jarvis.memory.scope import MAIN_AGENT, MemoryScope
from jarvis.memory.types import MemoryKind

Outcome = Literal["success", "failure"]


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
    scope: ScopeSpec | None = None  # 없으면 사례의 scope 를 쓴다
    at: str | None = None  # ISO 날짜. 지식 갱신처럼 순서가 중요한 사례용
    importance: float | None = None
    rehearsal_count: int = 0  # 되뇌기 횟수. 감쇠 저항 검증용
    skill: str | None = None  # 절차 기억: 스킬 이름
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    # 일화 메타데이터. 재설계의 EDM 이 저장하는 값이고, 기존 저장소는 본문만 남긴다
    task_type: str | None = None
    outcome: Outcome | None = None


class EpisodeFilter(BaseModel):
    """cherry-pick 조건. 비운 칸은 조건이 아니다."""

    task_type: str | None = None
    outcome: Outcome | None = None
    since: str | None = None  # ISO 날짜, 포함
    until: str | None = None  # ISO 날짜, 포함


class Expect(BaseModel):
    contains: list[str] = Field(default_factory=list)  # 상위 top_k 안에 전부 있어야 한다
    not_contains: list[str] = Field(default_factory=list)  # 하나라도 나오면 누수
    empty: bool = False  # 아무것도 나오지 않아야 한다(기권)
    top_k: int = 3
    distinct: bool = False  # 같은 결과가 두 번 나오면 실패. 두 번 돌린 정제가 항목을 늘리지 않는지 본다


class EvalCase(BaseModel):
    suite: str
    case: str
    setup: list[SetupStep]
    scope: ScopeSpec
    probe: str
    # procedures 는 스킬 이름, episodes 는 filter 로 고른 일화, candidates 는 정제를 두 번 돌린 뒤의 절차 후보 task_type
    probe_kind: Literal["recall", "procedures", "episodes", "candidates"] = "recall"
    filter: EpisodeFilter | None = None
    # 읽는 에이전트별 층별 허락 목록. {"main": {"edm": ["self", "karen"], "pdm": ["self"]}}. 없으면 [self]
    policy: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    expect: Expect

    def step_scope(self, step: SetupStep) -> MemoryScope:
        return (step.scope or self.scope).to_scope()


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


# ── 턴 거리별 보존 스위트 ────────────────────────────────────────────────────────
# 사실을 말하고 distance 턴 뒤에 묻는다. 답이 모델 컨텍스트(최근 턴 창, 회상 블록)에 있어야 한다.


class RetentionConfig(BaseModel):
    """기본값은 운영 설정(config.MemorySettings)과 같다."""

    stm_turns: int = 3


class RetentionCase(BaseModel):
    suite: str
    case: str
    fact: str  # 첫 턴의 사용자 발화
    question: str
    answer: str  # 마지막 컨텍스트에 이 글자가 있어야 한다
    distance: int  # 사실과 질문 사이의 채움 턴 수
    user_chars: int = 200
    assistant_chars: int = 800
    config: RetentionConfig = Field(default_factory=RetentionConfig)


def load_retention_cases(path: Path) -> list[RetentionCase]:
    cases: list[RetentionCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(RetentionCase.model_validate(json.loads(line)))
    return cases
