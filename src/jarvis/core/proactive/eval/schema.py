"""[core] proactive 평가 사례(jsonl 한 줄)의 형식. 프레임을 주면 정책만, 상황을 주면 엔진까지 잰다."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Turn(BaseModel):
    role: Literal["user", "assistant"] = "user"
    text: str


class Situation(BaseModel):
    """사고 엔진에 넣을 입력. 문자열만 받는다(엔진이 MCP 나 저장소를 모르는 것과 같은 경계)."""

    history: list[Turn] = Field(default_factory=list)
    open_loops: list[str] = Field(default_factory=list)
    external_events: list[str] = Field(default_factory=list)
    user_model: str = ""


class PolicySpec(BaseModel):
    confidence_threshold: float = 0.6
    cooldown_sec: int = 300
    spoke_before_sec: float | None = None  # 같은 세션이 이만큼 전에 이미 말했다(쿨다운 검증용)
    awaiting_reply: bool = False  # 그 말에 사용자가 아직 답하지 않았다. 거짓이면 답한 뒤로 본다


class ProactiveExpect(BaseModel):
    speak: bool
    mentions: list[str] = Field(default_factory=list)  # speak 일 때 메시지에 들어 있어야 하는 문자열
    autonomous_tools: list[str] = Field(default_factory=list)  # 저위험 자율 행동으로 분류돼야 하는 도구
    approval_tools: list[str] = Field(default_factory=list)  # 승인 대상(고위험)으로 분류돼야 하는 도구


class ProactiveCase(BaseModel):
    suite: str
    case: str
    frame: dict[str, Any] | None = None  # ThoughtFrame 필드. 있으면 엔진을 건너뛰고 정책만 잰다
    situation: Situation | None = None  # 없으면 frame 이 필수
    policy: PolicySpec = Field(default_factory=PolicySpec)
    expect: ProactiveExpect

    @model_validator(mode="after")
    def _frame_or_situation(self) -> "ProactiveCase":
        if self.frame is None and self.situation is None:
            raise ValueError(f"case '{self.case}': frame 또는 situation 중 하나는 있어야 한다")
        return self

    @property
    def needs_engine(self) -> bool:
        return self.frame is None


def load_cases(path: Path) -> list[ProactiveCase]:
    return [
        ProactiveCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
