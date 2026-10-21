"""[agent_layer] 세션 메타와 메시지를 세션별 JSONL 파일에 append 로 영속한다."""

import json
import aiofiles
import builtins
from pathlib import Path

from jarvis.agent_layer.session.protocol import (
    PROACTIVE_ENTRY,
    SessionEntry,
    SessionMetadata,
    SessionRepo,
    deserialize_message,
)
from jarvis.model_layer.types import Message
from jarvis.memory.scope import MAIN_AGENT


class JsonlSessionRepo(SessionRepo):
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

    async def create(
        self, session_id: str | None = None, cwd: str = ".", agent_id: str = MAIN_AGENT
    ) -> SessionMetadata:
        self._root.mkdir(parents=True, exist_ok=True)
        sid = session_id or self._new_id()
        # Idempotent: return existing meta rather than overwriting
        existing = await self.get_meta(sid)
        if existing is not None:
            return existing
        now = self._now_ms()
        meta = SessionMetadata(
            session_id=sid,
            cwd=cwd,
            created_at=now,
            updated_at=now,
            message_count=0,
            agent_id=agent_id,
        )
        meta_path = self._meta_path(sid)
        async with aiofiles.open(meta_path, "w") as f:
            await f.write(meta.model_dump_json())
        self._session_path(sid).touch()
        return meta

    async def get_meta(self, session_id: str) -> SessionMetadata | None:
        meta_path = self._meta_path(session_id)
        if not meta_path.exists():
            return None
        async with aiofiles.open(meta_path) as f:
            return SessionMetadata.model_validate(json.loads(await f.read()))

    async def list(self, cwd: str = "") -> builtins.list[SessionMetadata]:
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

    async def get_messages(self, session_id: str) -> builtins.list[Message]:
        messages = []
        for entry in await self._read_entries(session_id, "message"):
            msg = deserialize_message(entry.content)
            if msg:
                messages.append(msg)
        return messages

    async def append_proactive(self, session_id: str, message_id: str, text: str) -> None:
        entry = SessionEntry(
            id=message_id,
            timestamp=self._now_ms(),
            type=PROACTIVE_ENTRY,
            content={"text": text},
        )
        async with aiofiles.open(self._session_path(session_id), "a") as f:
            await f.write(entry.model_dump_json() + "\n")

    async def get_proactive(self, session_id: str) -> builtins.list[SessionEntry]:
        # append 만 하는 파일이라 같은 id 가 두 줄일 수 있다. 처음 남긴 줄을 쓴다
        first: dict[str, SessionEntry] = {}
        for entry in await self._read_entries(session_id, PROACTIVE_ENTRY):
            first.setdefault(entry.id, entry)
        return list(first.values())

    async def _read_entries(self, session_id: str, entry_type: str) -> builtins.list[SessionEntry]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        entries = []
        async with aiofiles.open(path) as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = SessionEntry.model_validate(json.loads(line))
                except Exception:
                    continue
                if entry.type == entry_type:
                    entries.append(entry)
        return entries

    async def append(self, session_id: str, message: Message) -> str:
        entry_id = self._new_id()
        entry = SessionEntry(
            id=entry_id,
            parent_id=None,
            timestamp=self._now_ms(),
            type="message",
            content=self._message_content(message),
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
        branch_id = self._new_id()
        now = self._now_ms()

        # Read parent messages
        parent_messages = await self.get_messages(parent_session_id)
        parent_meta = await self.get_meta(parent_session_id)

        # Create branch JSONL by copying parent entries
        branch_path = self._session_path(branch_id)
        async with aiofiles.open(branch_path, "w") as f:
            for msg in parent_messages:
                entry = SessionEntry(
                    id=self._new_id(),
                    parent_id=parent_session_id,
                    timestamp=now,
                    type="message",
                    content=self._message_content(msg),
                )
                await f.write(entry.model_dump_json() + "\n")

        meta = SessionMetadata(
            session_id=branch_id,
            cwd=".",
            created_at=now,
            updated_at=now,
            message_count=len(parent_messages),
            parent_id=parent_session_id,
            agent_id=parent_meta.agent_id if parent_meta is not None else MAIN_AGENT,
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
        data["updated_at"] = self._now_ms()
        data["message_count"] = data.get("message_count", 0) + 1
        async with aiofiles.open(meta_path, "w") as f:
            await f.write(json.dumps(data))


