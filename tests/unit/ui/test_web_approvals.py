"""승인 요청은 세션의 연결 전부에 가고, 먼저 온 답이 이긴다."""

import pytest
import asyncio

from jarvis.ui.web.approvals import Connection, SessionApprovals


class FakeConn(Connection):
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


def _broker(timeout: float = 5.0) -> SessionApprovals:
    ids = iter(["a1", "a2"])
    return SessionApprovals(timeout_sec=timeout, new_id=lambda: next(ids))


async def test_every_connection_gets_request_and_first_answer_wins():
    broker, c1, c2 = _broker(), FakeConn(), FakeConn()
    await broker.attach(c1)
    await broker.attach(c2)
    task = asyncio.create_task(broker.request("rm -rf build", "위험", "rm -rf *"))
    await asyncio.sleep(0)
    assert [m["type"] for m in c1.sent] == ["approval_request"] and c1.sent[0]["id"] == "a1"
    assert c2.sent[0] == c1.sent[0]
    assert broker.resolve("a1", approved=True, always=True) is True
    assert broker.resolve("a1", approved=False) is False  # 늦은 답
    assert await task == "always"
    assert c1.sent[-1] == {"type": "approval_resolved", "id": "a1"} and c2.sent[-1] == c1.sent[-1]


async def test_late_connection_sees_pending_request():
    broker, c1, c2 = _broker(), FakeConn(), FakeConn()
    await broker.attach(c1)
    task = asyncio.create_task(broker.request("ls", "확인"))
    await asyncio.sleep(0)
    await broker.attach(c2)
    assert c2.sent[0]["type"] == "approval_request" and c2.sent[0]["id"] == "a1"
    broker.resolve("a1", approved=False)
    assert await task is False


async def test_timeout_denies_and_closes_everywhere():
    broker, c1 = _broker(timeout=0.01), FakeConn()
    await broker.attach(c1)
    # 거부와 같지만 사용자에게 다르게 알리도록 timeout 으로 돌려주고, 닫는 알림에도 싣는다
    assert await broker.request("ls", "확인") == "timeout"
    assert c1.sent[-1] == {"type": "approval_resolved", "id": c1.sent[-1]["id"], "timeout": True}
    assert broker.pending_ids == []


async def test_no_connection_denies_immediately():
    assert await _broker().request("ls", "확인") is False


async def test_detached_connection_gets_nothing():
    broker, c1 = _broker(timeout=0.01), FakeConn()
    await broker.attach(c1)
    broker.detach(c1)
    assert await broker.request("ls", "확인") is False
    assert c1.sent == []


@pytest.mark.parametrize("unknown", ["nope", ""])
def test_resolve_unknown_id_is_false(unknown):
    assert _broker().resolve(unknown, approved=True) is False


async def test_command_truncated_to_500():
    broker, c1 = _broker(timeout=0.01), FakeConn()
    await broker.attach(c1)
    await broker.request("x" * 1000, "이유")
    assert len(c1.sent[0]["command"]) == 500
