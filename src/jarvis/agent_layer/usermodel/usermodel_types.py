"""[agent_layer] 누적 기억에서 증류한 안정적 사용자 모델과 사고 프롬프트용 블록 변환을 정의한다."""

import time
from pydantic import BaseModel, Field


class UserModel(BaseModel):
    """누적 기억에서 증류한 안정적 사용자 모델 (Tier 3 D1).

    episodic 회상(휘발적·문맥적)과 달리, 사용자의 선호·작업 방식·반복 패턴 같은
    "오래 가는 특성"을 담는다. 사고 시 컨텍스트로 주입돼 "사용자를 아는" 판단을 돕는다.
    """

    summary: str = ""  # 한 문단 요약
    traits: list[str] = Field(default_factory=list)  # 선호/패턴/작업 방식 항목
    source_count: int = 0  # 증류에 사용한 소스 개수(관찰 가능성)
    updated_at: int = Field(default_factory=lambda: int(time.time() * 1000))

    def is_empty(self) -> bool:
        return not self.summary and not self.traits

    def as_context(self) -> str:
        """사고 프롬프트에 주입할 사람이 읽을 수 있는 블록(비면 빈 문자열)."""
        if self.is_empty():
            return ""
        lines = ["[사용자 모델]"]
        if self.summary:
            lines.append(self.summary)
        if self.traits:
            lines.extend(f"- {t}" for t in self.traits)
        return "\n".join(lines)
