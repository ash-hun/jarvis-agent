"""[agent_layer] 세션 저장소 기본 클래스와 세션 엔트리, 메타 모델, 메시지 역직렬화를 둔다."""

import json
import time
import uuid
import builtins
from typing import Any
from pydantic import BaseModel

from jarvis.model_layer.types import AssistantMessage, Message, ToolResultMessage, UserMessage
from jarvis.memory.scope import MAIN_AGENT

# 먼저 건넨 말(🔔). 대화 기록이 아니라 get_messages 에는 섞이지 않는다
PROACTIVE_ENTRY = "proactive"
# 🔔 에 사용자가 피드백(수락/무시)으로 답했다. 재시작 뒤 응답 대기를 다시 걸지 않게 한다
PROACTIVE_ACK_ENTRY = "proactive_ack"


class SessionEntry(BaseModel):
    id: str
    parent_id: str | None = None
    timestamp: int
    type: str  # "message" | "branch" | "compaction" | "proactive" | "proactive_ack"
    content: dict[str, Any]


class SessionMetadata(BaseModel):
    session_id: str
    cwd: str
    created_at: int
    updated_at: int
    message_count: int
    parent_id: str | None = None
    # 세션을 만든 최상위 에이전트. 만든 뒤에는 바뀌지 않는다. 옛 세션은 main
    agent_id: str = MAIN_AGENT


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

    async def create(
        self, session_id: str | None = None, cwd: str = ".", agent_id: str = MAIN_AGENT
    ) -> SessionMetadata:
        """없으면 만들고 있으면 그대로 둔다. 이미 있는 세션의 에이전트는 바꾸지 않는다."""
        raise NotImplementedError("세션 저장 방식은 저장 매체마다 다르다")

    async def get_meta(self, session_id: str) -> SessionMetadata | None:
        """세션 메타. 없으면 None."""
        raise NotImplementedError("메타 조회는 저장 매체마다 다르다")

    async def list(self, cwd: str = "") -> builtins.list[SessionMetadata]:
        raise NotImplementedError("세션 목록 조회는 저장 매체마다 다르다")

    async def get_messages(self, session_id: str) -> builtins.list[Message]:
        raise NotImplementedError("메시지 조회는 저장 매체마다 다르다")

    async def append(self, session_id: str, message: Message) -> str:
        raise NotImplementedError("메시지 저장은 저장 매체마다 다르다")

    async def append_proactive(
        self, session_id: str, message_id: str, text: str, entry_type: str = PROACTIVE_ENTRY
    ) -> None:
        """먼저 건넨 말(이나 그 말의 피드백)을 남긴다. 같은 message_id 는 몇 번 불러도 하나다."""
        raise NotImplementedError("🔔 저장은 저장 매체마다 다르다")

    async def get_proactive(
        self, session_id: str, entry_type: str = PROACTIVE_ENTRY
    ) -> builtins.list[SessionEntry]:
        """남긴 순서대로. content 는 {"text": ...}."""
        raise NotImplementedError("🔔 조회는 저장 매체마다 다르다")

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
