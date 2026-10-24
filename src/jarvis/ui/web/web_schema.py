"""[ui] Web HUD REST 요청 본문 모델. 값 검증은 핸들러가 해서 예전과 같은 400 메시지를 돌려준다."""

from pydantic import BaseModel, Field, JsonValue


class OpenLoopStatusRequest(BaseModel):
    status: JsonValue = Field(
        default=None, description="바꿀 상태. done, dismissed, 또는 다시 여는 open", examples=["done"]
    )


class ScheduleToggleRequest(BaseModel):
    enabled: JsonValue = Field(default=None, description="켤지 여부. true 또는 false", examples=[False])


class CreateSessionRequest(BaseModel):
    agent: str | None = Field(default=None, description="세션을 맡을 에이전트 id. 비우면 main", examples=["karen"])
