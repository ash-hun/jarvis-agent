from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from pydantic import BaseModel

from jarvis.model_layer.types import Message


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


@runtime_checkable
class SessionRepo(Protocol):
    async def create(self, session_id: str, cwd: str) -> SessionMetadata: ...

    async def list(self, cwd: str) -> list[SessionMetadata]: ...

    async def get_messages(self, session_id: str) -> list[Message]: ...

    async def append(self, session_id: str, message: Message) -> str: ...

    async def delete(self, session_id: str) -> None: ...
