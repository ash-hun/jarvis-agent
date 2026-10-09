from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class SessionRepo(Protocol):
    async def create(self, session_id: str, cwd: str) -> SessionMetadata: ...

    async def list(self, cwd: str) -> list[SessionMetadata]: ...

    async def get_messages(self, session_id: str) -> list[Message]: ...

    async def append(self, session_id: str, message: Message) -> str: ...

    async def delete(self, session_id: str) -> None: ...

    async def create_branch(self, parent_session_id: str) -> SessionMetadata: ...
