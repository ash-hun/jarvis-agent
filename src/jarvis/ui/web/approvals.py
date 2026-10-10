"""세션 하나의 승인 요청을 붙어 있는 모든 연결에 보내고 먼저 온 답을 쓴다."""

import asyncio
import uuid
from collections.abc import Callable
from typing import Any, Protocol

APPROVAL_TIMEOUT_SEC = 120.0


class Connection(Protocol):
    async def send(self, payload: dict) -> None: ...


class SessionApprovals:
    """연결은 오가도 세션당 하나. 샌드박스 콜백은 이 객체의 request 로 고정된다."""

    def __init__(
        self,
        timeout_sec: float = APPROVAL_TIMEOUT_SEC,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._timeout_sec = timeout_sec
        self._new_id = new_id
        self._connections: set[Any] = set()
        self._pending: dict[str, tuple[asyncio.Future[bool | str], dict]] = {}

    async def attach(self, conn: Connection) -> None:
        """기다리는 요청이 있으면 새 연결에도 바로 보여준다."""
        self._connections.add(conn)
        for _, payload in list(self._pending.values()):
            await conn.send(payload)

    def detach(self, conn: Connection) -> None:
        self._connections.discard(conn)

    @property
    def pending_ids(self) -> list[str]:
        return list(self._pending)

    async def request(self, command: str, reason: str, always_pattern: str = "") -> bool | str:
        if not self._connections:
            return False
        approval_id = self._new_id()
        future: asyncio.Future[bool | str] = asyncio.get_running_loop().create_future()
        payload = {
            "type": "approval_request",
            "id": approval_id,
            "command": command[:500],
            "reason": reason,
            "always_pattern": always_pattern,
        }
        self._pending[approval_id] = (future, payload)
        try:
            await self._broadcast(payload)
            return await asyncio.wait_for(future, timeout=self._timeout_sec)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(approval_id, None)
            await self._broadcast({"type": "approval_resolved", "id": approval_id})

    def resolve(self, approval_id: str, approved: bool, always: bool = False) -> bool:
        """먼저 온 답만 쓴다. always 는 approved 일 때만 의미가 있다. 늦은 답과 모르는 id 는 False."""
        entry = self._pending.get(approval_id)
        if entry is None or entry[0].done():
            return False
        entry[0].set_result("always" if approved and always else approved)
        return True

    async def _broadcast(self, payload: dict) -> None:
        for conn in list(self._connections):
            await conn.send(payload)
