from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import aiofiles

from jarvis.agent_layer.session.protocol import SessionEntry, SessionMetadata, deserialize_message
from jarvis.model_layer.types import Message


class JsonlSessionRepo:
    """
    JSONL 기반 세션 영속성. Pi: jsonl-repo.ts 완전 동일 패턴.
    - append-only, git-friendly
    - parentId 트리 구조로 브랜칭 지원
    """

    def __init__(self, sessions_root: str = "~/.jarvis/sessions") -> None:
        self._root = Path(sessions_root).expanduser()

    def _session_path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.jsonl"

    def _meta_path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.meta.json"

    async def create(self, session_id: str | None = None, cwd: str = ".") -> SessionMetadata:
        self._root.mkdir(parents=True, exist_ok=True)
        sid = session_id or str(uuid.uuid4())
        meta_path = self._meta_path(sid)
        # Idempotent: return existing meta rather than overwriting
        if meta_path.exists():
            async with aiofiles.open(meta_path) as f:
                data = json.loads(await f.read())
            return SessionMetadata.model_validate(data)
        now = int(time.time() * 1000)
        meta = SessionMetadata(
            session_id=sid,
            cwd=cwd,
            created_at=now,
            updated_at=now,
            message_count=0,
        )
        async with aiofiles.open(meta_path, "w") as f:
            await f.write(meta.model_dump_json())
        self._session_path(sid).touch()
        return meta

    async def list(self, cwd: str = "") -> list[SessionMetadata]:
        if not self._root.exists():
            return []
        metas = []
        for meta_file in self._root.glob("*.meta.json"):
            try:
                async with aiofiles.open(meta_file) as f:
                    data = json.loads(await f.read())
                meta = SessionMetadata.model_validate(data)
                if not cwd or meta.cwd == cwd:
                    metas.append(meta)
            except Exception:
                continue
        return sorted(metas, key=lambda m: m.updated_at, reverse=True)

    async def get_messages(self, session_id: str) -> list[Message]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        messages = []
        async with aiofiles.open(path) as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = SessionEntry.model_validate(json.loads(line))
                    if entry.type == "message":
                        msg = deserialize_message(entry.content)
                        if msg:
                            messages.append(msg)
                except Exception:
                    continue
        return messages

    async def append(self, session_id: str, message: Message) -> str:
        entry_id = str(uuid.uuid4())
        entry = SessionEntry(
            id=entry_id,
            parent_id=None,
            timestamp=int(time.time() * 1000),
            type="message",
            content=json.loads(message.model_dump_json()),
        )
        async with aiofiles.open(self._session_path(session_id), "a") as f:
            await f.write(entry.model_dump_json() + "\n")

        await self._update_meta(session_id)
        return entry_id

    async def delete(self, session_id: str) -> None:
        self._session_path(session_id).unlink(missing_ok=True)
        self._meta_path(session_id).unlink(missing_ok=True)

    async def create_branch(self, parent_session_id: str) -> SessionMetadata:
        """부모 세션의 모든 메시지를 복사한 새 세션을 생성하고 parent_id를 설정한다."""
        self._root.mkdir(parents=True, exist_ok=True)
        branch_id = str(uuid.uuid4())
        now = int(time.time() * 1000)

        # Read parent messages
        parent_messages = await self.get_messages(parent_session_id)

        # Create branch JSONL by copying parent entries
        branch_path = self._session_path(branch_id)
        async with aiofiles.open(branch_path, "w") as f:
            for msg in parent_messages:
                entry = SessionEntry(
                    id=str(uuid.uuid4()),
                    parent_id=parent_session_id,
                    timestamp=now,
                    type="message",
                    content=json.loads(msg.model_dump_json()),
                )
                await f.write(entry.model_dump_json() + "\n")

        meta = SessionMetadata(
            session_id=branch_id,
            cwd=".",
            created_at=now,
            updated_at=now,
            message_count=len(parent_messages),
            parent_id=parent_session_id,
        )
        async with aiofiles.open(self._meta_path(branch_id), "w") as f:
            await f.write(meta.model_dump_json())
        return meta

    async def _update_meta(self, session_id: str) -> None:
        meta_path = self._meta_path(session_id)
        if not meta_path.exists():
            return
        async with aiofiles.open(meta_path) as f:
            data = json.loads(await f.read())
        data["updated_at"] = int(time.time() * 1000)
        data["message_count"] = data.get("message_count", 0) + 1
        async with aiofiles.open(meta_path, "w") as f:
            await f.write(json.dumps(data))


