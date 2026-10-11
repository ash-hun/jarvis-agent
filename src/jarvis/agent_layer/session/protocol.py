"""[agent_layer] 세션 저장소 기본 클래스와 세션 엔트리, 메타 모델, 메시지 역직렬화를 둔다."""

from __future__ import annotations

import builtins
import json
import time
import uuid
from typing import Any

from pydantic import BaseModel

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage, UserMessage


class SessionEntry(BaseModel):
    id: str
    parent_id: str | None = None
    timestamp: int
    type: str  # "message" | "branch" | "compaction"
    content: dict[str, Any]


class SessionMetadata(BaseModel):
    session_id: str
    cwd: str
    created_at: int
    updated_at: int
    message_count: int
    parent_id: str | None = None


def deserialize_message(content: dict[str, Any]) -> Message | None:
    """role 필드 기준으로 dict → Message 타입 역직렬화."""
    role = content.get("role")
    try:
        if role == "user":
            return UserMessage.model_validate(content)
        elif role == "assistant":
            return AssistantMessage.model_validate(content)
        elif role == "tool_result":
            return ToolResultMessage.model_validate(content)
    except Exception:
        return None
    return None


class SessionRepo:
    """세션 저장소 기본 클래스. 저장 매체(jsonl / postgres)가 공통으로 쓰는 id·시각·직렬화 도우미를 갖는다.

    저장 메서드는 매체마다 달라 기본 동작이 없다. 상속한 저장소가 모두 재정의한다.
    """

    async def create(self, session_id: str | None = None, cwd: str = ".") -> SessionMetadata:
        raise NotImplementedError("세션 저장 방식은 저장 매체마다 다르다")

    async def list(self, cwd: str = "") -> builtins.list[SessionMetadata]:
        raise NotImplementedError("세션 목록 조회는 저장 매체마다 다르다")

    async def get_messages(self, session_id: str) -> builtins.list[Message]:
        raise NotImplementedError("메시지 조회는 저장 매체마다 다르다")

    async def append(self, session_id: str, message: Message) -> str:
        raise NotImplementedError("메시지 저장은 저장 매체마다 다르다")

    async def delete(self, session_id: str) -> None:
        raise NotImplementedError("세션 삭제는 저장 매체마다 다르다")

    async def create_branch(self, parent_session_id: str) -> SessionMetadata:
        raise NotImplementedError("브랜치 복사는 저장 매체마다 다르다")

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _message_content(message: Message) -> dict[str, Any]:
        """저장용 dict. model_dump 대신 JSON 왕복으로 JSON 에 담기는 값만 남긴다."""
        content: dict[str, Any] = json.loads(message.model_dump_json())
        return content
