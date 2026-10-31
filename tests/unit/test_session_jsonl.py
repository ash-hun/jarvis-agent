"""session 의 JsonlSessionRepo: 만들기 멱등, 분기 복사, 에이전트 고정, 먼저 건넨 말 분리, 동시 생성을 검증한다."""

import json
import pytest
import asyncio

from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.model_layer.model_types import UserMessage


async def test_create_twice_keeps_the_existing_session(jsonl_repo):
    first = await jsonl_repo.create(session_id="sess-1", cwd="/tmp")
    await jsonl_repo.append("sess-1", UserMessage(content="hello"))

    again = await jsonl_repo.create(session_id="sess-1", cwd="/tmp")

    assert (first.message_count, first.parent_id) == (0, None)
    assert first.created_at > 0
    assert again.session_id == "sess-1"
    assert again.message_count > 0, "create() must be idempotent: must not reset message_count"


async def test_append_returns_a_new_entry_id_each_time(jsonl_repo):
    await jsonl_repo.create(session_id="s")

    ids = {await jsonl_repo.append("s", UserMessage(content="안녕")) for _ in range(2)}

    assert len(ids) == 2


async def test_session_agent_is_fixed_at_creation(tmp_path):
    repo = JsonlSessionRepo(str(tmp_path))
    assert await repo.get_meta("k1") is None

    created = await repo.create(session_id="k1", agent_id="karen")
    again = await repo.create(session_id="k1", agent_id="main")
    branch = await repo.create_branch("k1")

    assert created.agent_id == again.agent_id == "karen"
    assert (await repo.get_meta("k1")).agent_id == "karen"
    assert branch.agent_id == "karen"


async def test_old_meta_without_agent_reads_as_main(tmp_path):
    (tmp_path / "old.meta.json").write_text(json.dumps(
        {"session_id": "old", "cwd": ".", "created_at": 1, "updated_at": 1, "message_count": 0}
    ))

    meta = await JsonlSessionRepo(str(tmp_path)).get_meta("old")

    assert meta.agent_id == "main"


@pytest.mark.parametrize("contents", [[], ["First message", "Second message"]])
async def test_create_branch_copies_history_and_points_to_parent(jsonl_repo, contents):
    await jsonl_repo.create(session_id="parent-sess")
    for text in contents:
        await jsonl_repo.append("parent-sess", UserMessage(content=text))

    branch = await jsonl_repo.create_branch("parent-sess")

    assert branch.parent_id == "parent-sess"
    assert branch.session_id != "parent-sess"
    assert branch.message_count == len(contents)
    assert [m.content for m in await jsonl_repo.get_messages(branch.session_id)] == contents


async def test_create_branch_twice_gives_distinct_sessions_listed_under_parent(jsonl_repo):
    await jsonl_repo.create(session_id="root-session")
    await jsonl_repo.append("root-session", UserMessage(content="hi"))

    b1 = await jsonl_repo.create_branch("root-session")
    b2 = await jsonl_repo.create_branch("root-session")

    assert b1.session_id != b2.session_id
    listed = {s.session_id: s.parent_id for s in await jsonl_repo.list()}
    assert listed == {"root-session": None, b1.session_id: "root-session", b2.session_id: "root-session"}


async def test_proactive_is_idempotent_and_kept_out_of_messages(tmp_path):
    repo = JsonlSessionRepo(sessions_root=str(tmp_path))
    await repo.create("s")
    await repo.append("s", UserMessage(content="안녕"))

    await repo.append_proactive("s", "m1", "먼저 하는 말")
    await repo.append_proactive("s", "m1", "먼저 하는 말")
    await repo.append_proactive("s", "m2", "두 번째 말")

    said = await repo.get_proactive("s")
    assert [(e.id, e.content["text"]) for e in said] == [("m1", "먼저 하는 말"), ("m2", "두 번째 말")]
    assert len(await repo.get_messages("s")) == 1
    assert (await repo.get_meta("s")).message_count == 1


def test_concurrent_create_and_read_never_sees_a_half_written_meta(tmp_path):
    repo = JsonlSessionRepo(str(tmp_path))

    async def race(sid: str) -> None:
        # 화면 둘이 아직 없는 세션에 동시에 붙는다. 한쪽이 쓰는 동안 다른 쪽이 읽는다
        await asyncio.gather(repo.create(sid), repo.get_meta(sid), repo.create(sid), repo.get_meta(sid))

    async def main() -> None:
        for i in range(200):
            await race(f"s{i}")

    asyncio.run(main())

    assert len(list(tmp_path.glob("*.meta.json"))) == 200
    assert list(tmp_path.glob("*.tmp")) == []
