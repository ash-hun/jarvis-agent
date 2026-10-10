from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

MIN_CONTAINMENT_CHARS = 6  # 이보다 짧은 조각의 포함은 우연이 많다


class OpenLoop(BaseModel):
    """추적 중인 약속/미완 작업 1건 (Tier 2).

    사용자가 흘린 "나중에 ~할게", "~ 확인 부탁" 같은 미완 obligation을 추적한다.
    상태 전이: open → done | dismissed.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    description: str
    status: Literal["open", "done", "dismissed"] = "open"
    origin_session: str | None = None
    # 만기 힌트(epoch ms). 엄격한 due 연산보다는 reflection이 [지금]과 함께 보고 판단.
    due_ms: int | None = None
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = Field(default_factory=lambda: int(time.time() * 1000))


def normalize_description(text: str) -> str:
    """중복 판정용 정규화 — 공백 정리 + 소문자."""
    return " ".join(text.split()).lower()


def same_loop(a: str, b: str) -> bool:
    """정규화해 같거나, 짧은 쪽이 긴 쪽에 통째로 들어가면 같은 약속으로 본다."""
    x, y = normalize_description(a), normalize_description(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long = sorted((x, y), key=len)
    # ponytail: 포함 관계만 본다("로그 확인" ⊂ "배포 로그 확인"), 바꿔 말한 약속이 계속 쌓이면 임베딩 유사도로
    return len(short) >= MIN_CONTAINMENT_CHARS and short in long
