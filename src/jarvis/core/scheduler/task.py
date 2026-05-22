from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ScheduledTask(BaseModel):
    """스케줄된 작업 정의 — ~/.jarvis/schedules/*.yaml 또는 /schedule 슬래시 명령으로 생성."""

    name: str
    schedule: str  # cron expression: "0 9 * * *"
    prompt: str
    session_id: str | None = None  # None = 실행마다 새 세션
    tools_allowed: list[str] = Field(default_factory=list)  # 빈 리스트 = 전체 허용
    enabled: bool = True
    description: str = ""
    run_until: datetime | None = None  # 이 시각 이후 자동 만료 (슬래시 명령용)
