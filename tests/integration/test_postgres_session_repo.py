"""PostgresSessionRepo 통합 테스트.

testcontainers로 실제 PostgreSQL 컨테이너를 띄워 검증한다.
Docker가 없거나 testcontainers/asyncpg가 설치되지 않으면 자동 skip.
"""

from __future__ import annotations

import pytest

# ── Docker / 패키지 가용성 검사 ────────────────────────────────────────────────

testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("asyncpg", reason="asyncpg not installed")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def postgres_dsn():
    """모듈 스코프 — 테스트 파일 전체에서 컨테이너 1개 공유."""
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            # get_connection_url()은 psycopg2 URL 반환 → asyncpg용으로 변환
            dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
            yield dsn
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


@pytest.fixture
async def repo(postgres_dsn: str):
    """테스트별 신선한 PostgresSessionRepo — 종료 시 풀 닫음."""
    from jarvis.agent_layer.session.postgres import PostgresSessionRepo

    r = PostgresSessionRepo(dsn=postgres_dsn)
    yield r
    await r.close()


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _user_msg(text: str):
    from jarvis.model_layer.types import UserMessage
    return UserMessage(content=text)


def _assistant_msg(text: str):
    from jarvis.model_layer.types import AssistantMessage, TextContent, Usage
    return AssistantMessage(
        content=[TextContent(text=text)],
        provider="faux",
        model="faux-model",
        usage=Usage(),
        stop_reason="stop",
    )


# ── create ────────────────────────────────────────────────────────────────────

class TestCreate:
    async def test_create_returns_metadata(self, repo):
        meta = await repo.create(session_id="sess-create-1", cwd="/tmp")
        assert meta.session_id == "sess-create-1"
        assert meta.cwd == "/tmp"
        assert meta.message_count == 0
        assert meta.parent_id is None

    async def test_create_idempotent(self, repo):
        await repo.create(session_id="sess-idem", cwd="/tmp")
        await repo.append("sess-idem", _user_msg("hello"))

        meta2 = await repo.create(session_id="sess-idem", cwd="/tmp")
        assert meta2.session_id == "sess-idem"
        # ON CONFLICT DO NOTHING — message_count는 리셋되지 않음
        assert meta2.message_count == 0  # create 반환값은 초기값, DB 업데이트는 append

    async def test_create_auto_uuid(self, repo):
        meta = await repo.create(cwd="/home")
        assert len(meta.session_id) == 36  # UUID 형식


# ── list ──────────────────────────────────────────────────────────────────────

class TestList:
    async def test_list_returns_created_sessions(self, repo):
        await repo.create(session_id="sess-list-a", cwd="/list-test")
        await repo.create(session_id="sess-list-b", cwd="/list-test")

        sessions = await repo.list()
        ids = [s.session_id for s in sessions]
        assert "sess-list-a" in ids
        assert "sess-list-b" in ids

    async def test_list_filter_by_cwd(self, repo):
        await repo.create(session_id="sess-cwd-match", cwd="/specific")
        await repo.create(session_id="sess-cwd-other", cwd="/other")

        sessions = await repo.list(cwd="/specific")
        ids = [s.session_id for s in sessions]
        assert "sess-cwd-match" in ids
        assert "sess-cwd-other" not in ids

    async def test_list_ordered_by_updated_at_desc(self, repo):
        await repo.create(session_id="sess-order-old", cwd="/order")
        await repo.append("sess-order-old", _user_msg("first"))
        await repo.create(session_id="sess-order-new", cwd="/order")
        await repo.append("sess-order-new", _user_msg("second"))

        sessions = await repo.list(cwd="/order")
        ids = [s.session_id for s in sessions]
        assert ids.index("sess-order-new") < ids.index("sess-order-old")


# ── append + get_messages ─────────────────────────────────────────────────────

class TestAppendAndGetMessages:
    async def test_append_user_message(self, repo):
        await repo.create(session_id="sess-append-u")
        entry_id = await repo.append("sess-append-u", _user_msg("hello"))
        assert isinstance(entry_id, str) and len(entry_id) == 36

        msgs = await repo.get_messages("sess-append-u")
        assert len(msgs) == 1
        assert msgs[0].content == "hello"

    async def test_append_assistant_message(self, repo):
        await repo.create(session_id="sess-append-a")
        await repo.append("sess-append-a", _assistant_msg("world"))

        msgs = await repo.get_messages("sess-append-a")
        assert len(msgs) == 1
        assert msgs[0].text() == "world"

    async def test_append_preserves_order(self, repo):
        await repo.create(session_id="sess-order-msgs")
        for i in range(5):
            await repo.append("sess-order-msgs", _user_msg(f"msg-{i}"))

        msgs = await repo.get_messages("sess-order-msgs")
        assert len(msgs) == 5
        for i, msg in enumerate(msgs):
            assert msg.content == f"msg-{i}"

    async def test_append_updates_message_count(self, repo):
        await repo.create(session_id="sess-count")
        await repo.append("sess-count", _user_msg("a"))
        await repo.append("sess-count", _user_msg("b"))

        sessions = await repo.list()
        sess = next(s for s in sessions if s.session_id == "sess-count")
        assert sess.message_count == 2

    async def test_get_messages_empty_session(self, repo):
        await repo.create(session_id="sess-empty-msgs")
        msgs = await repo.get_messages("sess-empty-msgs")
        assert msgs == []


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    async def test_delete_removes_session(self, repo):
        await repo.create(session_id="sess-del")
        await repo.append("sess-del", _user_msg("to be deleted"))

        await repo.delete("sess-del")

        sessions = await repo.list()
        ids = [s.session_id for s in sessions]
        assert "sess-del" not in ids

    async def test_delete_cascades_entries(self, repo):
        await repo.create(session_id="sess-cascade")
        await repo.append("sess-cascade", _user_msg("msg"))
        await repo.delete("sess-cascade")

        msgs = await repo.get_messages("sess-cascade")
        assert msgs == []

    async def test_delete_nonexistent_is_noop(self, repo):
        await repo.delete("nonexistent-session-id")  # 예외 없이 통과


# ── create_branch ─────────────────────────────────────────────────────────────

class TestCreateBranch:
    async def test_branch_copies_messages(self, repo):
        await repo.create(session_id="sess-branch-src")
        await repo.append("sess-branch-src", _user_msg("msg-1"))
        await repo.append("sess-branch-src", _user_msg("msg-2"))

        branch = await repo.create_branch("sess-branch-src")

        assert branch.parent_id == "sess-branch-src"
        assert branch.session_id != "sess-branch-src"
        assert branch.message_count == 2

        msgs = await repo.get_messages(branch.session_id)
        assert len(msgs) == 2
        assert msgs[0].content == "msg-1"
        assert msgs[1].content == "msg-2"

    async def test_branch_of_empty_session(self, repo):
        await repo.create(session_id="sess-branch-empty")
        branch = await repo.create_branch("sess-branch-empty")

        assert branch.parent_id == "sess-branch-empty"
        assert branch.message_count == 0
        assert await repo.get_messages(branch.session_id) == []

    async def test_branch_in_list(self, repo):
        await repo.create(session_id="sess-branch-list")
        branch = await repo.create_branch("sess-branch-list")

        sessions = await repo.list()
        ids = [s.session_id for s in sessions]
        assert branch.session_id in ids

        branch_in_list = next(s for s in sessions if s.session_id == branch.session_id)
        assert branch_in_list.parent_id == "sess-branch-list"

    async def test_multiple_branches_have_unique_ids(self, repo):
        await repo.create(session_id="sess-multi-branch")
        b1 = await repo.create_branch("sess-multi-branch")
        b2 = await repo.create_branch("sess-multi-branch")

        assert b1.session_id != b2.session_id
        assert b1.parent_id == b2.parent_id == "sess-multi-branch"

    async def test_branch_independent_from_parent(self, repo):
        """브랜치 생성 후 부모에 메시지 추가해도 브랜치에 영향 없음."""
        await repo.create(session_id="sess-branch-indep")
        await repo.append("sess-branch-indep", _user_msg("shared"))

        branch = await repo.create_branch("sess-branch-indep")
        await repo.append("sess-branch-indep", _user_msg("only-parent"))

        branch_msgs = await repo.get_messages(branch.session_id)
        assert len(branch_msgs) == 1
        assert branch_msgs[0].content == "shared"

    async def test_branch_nonexistent_parent_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            await repo.create_branch("no-such-parent")


# ── close / pool 재생성 ───────────────────────────────────────────────────────

class TestClose:
    async def test_close_then_reopen(self, postgres_dsn):
        from jarvis.agent_layer.session.postgres import PostgresSessionRepo

        r = PostgresSessionRepo(dsn=postgres_dsn)
        await r.create(session_id="sess-close-reopen")
        await r.close()

        # 닫은 후 재사용 — 풀 재생성되어야 함
        meta = await r.create(session_id="sess-close-reopen-2")
        assert meta.session_id == "sess-close-reopen-2"
        await r.close()

    async def test_close_idempotent(self, postgres_dsn):
        from jarvis.agent_layer.session.postgres import PostgresSessionRepo

        r = PostgresSessionRepo(dsn=postgres_dsn)
        await r.close()  # 풀 없이 닫아도 예외 없음
        await r.close()  # 두 번 닫아도 예외 없음
