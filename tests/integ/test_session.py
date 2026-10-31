"""session 기능: 세션 REST(목록, 만들기, 이력, 분기, 삭제)와 PostgresSessionRepo 저장소 계약을 검증한다."""

import pytest
import asyncio

pytest.importorskip("fastapi")

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, Usage, UserMessage  # noqa: E402
from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path)) as c:
        yield c


def _assistant(text: str) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)], provider="faux", model="faux-model", usage=Usage(), stop_reason="stop"
    )


def test_session_list_create_messages_and_delete_round_trip(client):
    assert "default" in client.get("/api/sessions").json()["sessions"]
    assert client.get("/api/sessions/default/messages").json()["messages"] == []

    created = client.post("/api/sessions")
    sid = created.json()["session_id"]
    with client.websocket_connect("/ws?session_id=wsnew") as ws:
        ws.receive_json()
    listed = client.get("/api/sessions").json()["sessions"]
    deleted = [client.delete(f"/api/sessions/{sid}") for _ in range(2)]

    assert created.status_code == 200 and sid and sid != "default"
    assert sid in listed and "wsnew" in listed
    assert deleted[0].json() == {"deleted": sid}
    assert deleted[1].status_code == 200
    assert sid not in client.get("/api/sessions").json()["sessions"]


def test_delete_session_with_live_connection_is_refused(client):
    with client.websocket_connect("/ws?session_id=wsdel") as ws:
        ws.receive_json()
        refused = client.delete("/api/sessions/wsdel")

    assert refused.status_code == 409
    assert client.delete("/api/sessions/wsdel").status_code == 200


def test_branch_copies_history_and_messages_are_text_only(monkeypatch, tmp_path):
    assembly = web_assembly(monkeypatch, tmp_path)
    repo = assembly.ctx.session_repo

    async def seed() -> None:
        await repo.append("default", UserMessage(content="안녕"))
        await repo.append("default", AssistantMessage(content=[TextContent(text="반가워요")]))
        await repo.append(
            "default", ToolResultMessage(tool_call_id="t1", tool_name="bash", content=[TextContent(text="out")])
        )

    asyncio.run(seed())
    expected = [{"role": "user", "text": "안녕"}, {"role": "assistant", "text": "반가워요"}]

    with web_client(assembly) as c:
        history = c.get("/api/sessions/default/messages").json()
        resp = c.post("/api/sessions/default/branch")
        branch_id = resp.json()["session_id"]
        listed = c.get("/api/sessions").json()["sessions"]
        branch_history = c.get(f"/api/sessions/{branch_id}/messages").json()

    assert history == {"messages": expected}
    assert resp.status_code == 200 and resp.json()["parent_id"] == "default"
    assert branch_id in listed
    assert branch_history == {"messages": expected}


# PostgresSessionRepo: 실 PostgreSQL 이 있어야 돌고, Docker 가 없으면 건너뛴다


@pytest.fixture(scope="module")
def postgres_dsn():
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


@pytest.fixture
async def repo(postgres_dsn: str):
    from jarvis.agent_layer.session.postgres import PostgresSessionRepo

    r = PostgresSessionRepo(dsn=postgres_dsn)
    yield r
    await r.close()


async def test_pg_create_is_idempotent_and_keeps_stored_meta(repo):
    meta = await repo.create(session_id="sess-idem", cwd="/tmp")
    await repo.append("sess-idem", UserMessage(content="hello"))

    again = await repo.create(session_id="sess-idem", cwd="/tmp", agent_id="karen")
    generated = await repo.create(cwd="/home")

    assert (meta.session_id, meta.cwd, meta.message_count, meta.parent_id) == ("sess-idem", "/tmp", 0, None)
    # ON CONFLICT DO NOTHING: 개수는 리셋되지 않고, 이미 있는 세션의 에이전트도 바뀌지 않는다
    assert (again.session_id, again.message_count, again.agent_id) == ("sess-idem", 1, "main")
    assert len(generated.session_id) == 36


async def test_pg_agent_is_stored_defaulted_and_kept_by_branch(repo):
    await repo.create(session_id="sess-karen", agent_id="karen")
    await repo.create(session_id="sess-main")

    branch = await repo.create_branch("sess-karen")

    assert (await repo.get_meta("sess-karen")).agent_id == "karen"
    assert (await repo.get_meta("sess-main")).agent_id == "main"
    assert await repo.get_meta("sess-none") is None
    assert branch.agent_id == "karen"
    assert (await repo.get_meta(branch.session_id)).agent_id == "karen"


async def test_pg_list_filters_by_cwd_newest_first(repo):
    await repo.create(session_id="sess-order-old", cwd="/order")
    await repo.append("sess-order-old", UserMessage(content="first"))
    await repo.create(session_id="sess-order-new", cwd="/order")
    await repo.append("sess-order-new", UserMessage(content="second"))
    await repo.create(session_id="sess-cwd-other", cwd="/other")

    every = [s.session_id for s in await repo.list()]
    ids = [s.session_id for s in await repo.list(cwd="/order")]

    assert {"sess-order-old", "sess-order-new", "sess-cwd-other"} <= set(every)
    assert "sess-cwd-other" not in ids
    assert ids.index("sess-order-new") < ids.index("sess-order-old")


async def test_pg_append_round_trips_messages_in_order(repo):
    await repo.create(session_id="sess-append")
    await repo.create(session_id="sess-empty")

    entry_id = await repo.append("sess-append", UserMessage(content="msg-0"))
    for i in range(1, 5):
        await repo.append("sess-append", UserMessage(content=f"msg-{i}"))
    await repo.append("sess-append", _assistant("world"))
    msgs = await repo.get_messages("sess-append")

    assert isinstance(entry_id, str) and len(entry_id) == 36
    assert [m.content for m in msgs[:5]] == [f"msg-{i}" for i in range(5)]
    assert msgs[5].text() == "world"
    assert next(s for s in await repo.list() if s.session_id == "sess-append").message_count == 6
    assert await repo.get_messages("sess-empty") == []


async def test_pg_same_ms_appends_keep_insert_order(repo, monkeypatch):
    # 한 턴의 tool_result 와 다음 assistant 는 같은 ms 에 저장된다
    monkeypatch.setattr(repo, "_now_ms", lambda: 1_000)
    await repo.create(session_id="sess-same-ms")

    for i in range(20):
        await repo.append("sess-same-ms", UserMessage(content=f"msg-{i}"))

    assert [m.content for m in await repo.get_messages("sess-same-ms")] == [f"msg-{i}" for i in range(20)]


async def test_pg_delete_cascades_and_missing_is_noop(repo):
    await repo.create(session_id="sess-del")
    await repo.append("sess-del", UserMessage(content="to be deleted"))

    await repo.delete("sess-del")
    await repo.delete("nonexistent-session-id")

    assert "sess-del" not in [s.session_id for s in await repo.list()]
    assert await repo.get_messages("sess-del") == []


async def test_pg_branch_copies_history_independently(repo):
    await repo.create(session_id="sess-branch-src")
    await repo.append("sess-branch-src", UserMessage(content="msg-1"))
    await repo.append("sess-branch-src", UserMessage(content="msg-2"))
    await repo.create(session_id="sess-branch-empty")

    branch = await repo.create_branch("sess-branch-src")
    second = await repo.create_branch("sess-branch-src")
    await repo.append("sess-branch-src", UserMessage(content="only-parent"))
    empty = await repo.create_branch("sess-branch-empty")
    listed = {s.session_id: s for s in await repo.list()}

    assert (branch.parent_id, branch.message_count) == ("sess-branch-src", 2)
    assert branch.session_id not in ("sess-branch-src", second.session_id)
    assert second.parent_id == "sess-branch-src"
    assert [m.content for m in await repo.get_messages(branch.session_id)] == ["msg-1", "msg-2"]
    assert listed[branch.session_id].parent_id == "sess-branch-src"
    assert (empty.parent_id, empty.message_count) == ("sess-branch-empty", 0)
    assert await repo.get_messages(empty.session_id) == []


async def test_pg_branch_of_missing_parent_raises(repo):
    with pytest.raises(ValueError, match="not found"):
        await repo.create_branch("no-such-parent")


async def test_pg_close_is_idempotent_and_pool_reopens(postgres_dsn):
    from jarvis.agent_layer.session.postgres import PostgresSessionRepo

    idle = PostgresSessionRepo(dsn=postgres_dsn)
    await idle.close()
    await idle.close()
    r = PostgresSessionRepo(dsn=postgres_dsn)
    await r.create(session_id="sess-close-reopen")
    await r.close()

    meta = await r.create(session_id="sess-close-reopen-2")
    await r.close()

    assert meta.session_id == "sess-close-reopen-2"


async def test_pg_proactive_is_idempotent_and_kept_out_of_messages(repo):
    await repo.create(session_id="proactive-s")
    await repo.append("proactive-s", UserMessage(content="안녕"))

    await repo.append_proactive("proactive-s", "pm1", "먼저 하는 말")
    await repo.append_proactive("proactive-s", "pm1", "먼저 하는 말")
    await repo.append_proactive("proactive-s", "pm2", "두 번째 말")
    said = await repo.get_proactive("proactive-s")

    assert [(e.id, e.content["text"]) for e in said] == [("pm1", "먼저 하는 말"), ("pm2", "두 번째 말")]
    assert len(await repo.get_messages("proactive-s")) == 1
    assert (await repo.get_meta("proactive-s")).message_count == 1
