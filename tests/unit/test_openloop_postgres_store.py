"""openloop 의 PostgresOpenLoopStore: 기본 클래스 상속, DB 없이 모르는 상태 거절, 행 변환을 검증한다."""

from jarvis.agent_layer.openloop import OpenLoopStore, PostgresOpenLoopStore
from jarvis.agent_layer.openloop.postgres_store import _row_to_loop

DSN = "postgresql://unused@localhost/none"  # 연결하지 않는다


def test_postgres_store_is_open_loop_store():
    assert issubclass(PostgresOpenLoopStore, OpenLoopStore)


async def test_update_status_rejects_unknown_status_without_db():
    assert await PostgresOpenLoopStore(DSN).update_status("x", "bogus") is False


def test_row_to_loop_maps_columns():
    row = {
        "id": "r1", "description": "전화하기", "status": "done", "origin_session": None,
        "due_ms": 5, "created_at": 1, "updated_at": 2, "agent_id": "karen",
    }

    loop = _row_to_loop(row)

    assert (loop.id, loop.description, loop.status, loop.origin_session) == ("r1", "전화하기", "done", None)
    assert loop.agent_id == "karen"
    assert (loop.due_ms, loop.created_at, loop.updated_at) == (5, 1, 2)
