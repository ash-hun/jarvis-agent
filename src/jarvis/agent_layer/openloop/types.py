from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field


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
