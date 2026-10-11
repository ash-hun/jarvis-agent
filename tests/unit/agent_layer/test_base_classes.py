"""[agent_layer] 교체 지점 기본 클래스(저장소, 엔진, 조립기, 싱크, 미들웨어)의 기본 동작과 상속 관계 테스트."""

import pytest

from jarvis.agent_layer.memory.chain import MemoryMiddlewareChain
from jarvis.agent_layer.memory.protocol import MemoryMiddleware
from jarvis.agent_layer.openloop import (
    InMemoryOpenLoopStore,
    JsonlOpenLoopStore,
    OpenLoop,
    OpenLoopStore,
    PostgresOpenLoopStore,
)
from jarvis.agent_layer.openloop.postgres_store import _row_to_loop
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.agent_layer.session.postgres import PostgresSessionRepo
from jarvis.agent_layer.session.protocol import SessionRepo
from jarvis.agent_layer.thought import (
    DefaultThoughtComposer,
    InnerThoughtEngine,
    InterpretationOnlyComposer,
    ThoughtComposer,
    ThoughtEngine,
    ThoughtFrame,
    ThoughtLog,
    ThoughtRequest,
    ThoughtSink,
)
from jarvis.agent_layer.usermodel import InMemoryUserModelStore, JsonlUserModelStore, UserModel, UserModelStore
from jarvis.model_layer.types import UserMessage

DSN = "postgresql://unused@localhost/none"  # 연결하지 않는 테스트만 쓴다


# ── OpenLoopStore ─────────────────────────────────────────────────────────────


def test_openloop_stores_share_base():
    assert isinstance(InMemoryOpenLoopStore(), OpenLoopStore)
    assert issubclass(JsonlOpenLoopStore, OpenLoopStore)
    assert issubclass(PostgresOpenLoopStore, OpenLoopStore)


@pytest.mark.asyncio
async def test_openloop_base_works_as_memory_store():
    store = OpenLoopStore()
    loop = OpenLoop(id="a", description="회의 준비", origin_session="s1", created_at=1)
    assert await store.add(loop) == "a"
    assert await store.get("a") is loop
    assert await store.list_open(session_id="s1") == [loop]
    assert await store.update_status("a", "done") is True
    assert await store.list_open() == []
    assert await store.all() == [loop]


@pytest.mark.asyncio
async def test_openloop_base_add_unique_twice_is_same():
    store = OpenLoopStore()
    first = await store.add_unique(OpenLoop(description="보고서 보내기", origin_session="s"))
    second = await store.add_unique(OpenLoop(description="보고서 보내기", origin_session="s"))
    assert first is not None and second is None
    assert len(await store.all()) == 1


@pytest.mark.asyncio
async def test_jsonl_update_status_appends_once_per_change(tmp_path):
    path = tmp_path / "loops.jsonl"
    store = JsonlOpenLoopStore(path=str(path))
    await store.add(OpenLoop(id="x", description="약속"))
    assert await store.update_status("x", "done") is True
    assert await store.update_status("x", "bogus") is False
    assert await store.update_status("missing", "done") is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_row_to_loop_maps_columns():
    row = {
        "id": "r1",
        "description": "전화하기",
        "status": "done",
        "origin_session": None,
        "due_ms": 5,
        "created_at": 1,
        "updated_at": 2,
    }
    loop = _row_to_loop(row)
    assert (loop.id, loop.description, loop.status, loop.origin_session) == ("r1", "전화하기", "done", None)
    assert (loop.due_ms, loop.created_at, loop.updated_at) == (5, 1, 2)


@pytest.mark.asyncio
async def test_postgres_rejects_unknown_status_without_db():
    assert await PostgresOpenLoopStore(DSN).update_status("x", "bogus") is False


# ── UserModelStore ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usermodel_base_save_get():
    store = UserModelStore()
    assert await store.get() is None
    model = UserModel(summary="요약")
    await store.save(model)
    assert await store.get() is model
    assert isinstance(InMemoryUserModelStore(), UserModelStore)


@pytest.mark.asyncio
async def test_jsonl_usermodel_corrupt_file_is_none(tmp_path):
    path = tmp_path / "um.json"
    path.write_text("{broken", encoding="utf-8")
    store = JsonlUserModelStore(path=str(path))
    assert isinstance(store, UserModelStore)
    assert await store.get() is None


# ── ThoughtEngine / ThoughtComposer / ThoughtSink ─────────────────────────────


@pytest.mark.asyncio
async def test_thought_engine_base_is_disabled(faux_model):
    assert await ThoughtEngine().think(ThoughtRequest(user_input="안녕")) is None
    assert isinstance(InnerThoughtEngine(model=faux_model), ThoughtEngine)


def test_thought_composer_base_uses_context_block():
    frame = ThoughtFrame(interpretation="해석", recalled=["기억"])
    assert ThoughtComposer().compose(frame) == frame.context_block()
    assert DefaultThoughtComposer().compose(frame) == ThoughtComposer().compose(frame)
    assert isinstance(InterpretationOnlyComposer(), ThoughtComposer)


class _ListSink(ThoughtSink):
    def __init__(self) -> None:
        self.frames: list[tuple[ThoughtFrame, str | None]] = []

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None:
        self.frames.append((frame, session_id))


@pytest.mark.asyncio
async def test_thought_sink_base_discards_and_log_nests():
    frame = ThoughtFrame(interpretation="x")
    await ThoughtSink().store(frame, "s")  # 예외 없이 버린다
    inner = _ListSink()
    outer = ThoughtLog([ThoughtLog([inner]), ThoughtSink()])
    assert isinstance(outer, ThoughtSink)
    await outer.store(frame, "s")
    assert inner.frames == [(frame, "s")]


# ── MemoryMiddleware ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_middleware_base_passes_through():
    stage = MemoryMiddleware()
    messages = [UserMessage(content="hi")]
    assert await stage.transform(messages, {}) is messages
    assert await stage.store(messages[0], {}) is None
    assert await stage.retrieve("q", {}) == []
    assert await stage.clear({}) is None


@pytest.mark.asyncio
async def test_chain_is_middleware_and_nests():
    inner = MemoryMiddlewareChain([MemoryMiddleware()])
    outer = MemoryMiddlewareChain([inner])
    assert isinstance(outer, MemoryMiddleware)
    messages = [UserMessage(content="hi")]
    assert await outer.transform(messages, {}) == messages
    assert await outer.retrieve("q", {}) == []


# ── SessionRepo ───────────────────────────────────────────────────────────────


def test_session_repos_share_base(tmp_path):
    assert isinstance(JsonlSessionRepo(sessions_root=str(tmp_path)), SessionRepo)
    assert isinstance(PostgresSessionRepo(DSN), SessionRepo)


@pytest.mark.asyncio
async def test_session_repo_base_has_no_storage():
    repo = SessionRepo()
    with pytest.raises(NotImplementedError):
        await repo.get_messages("s")
    with pytest.raises(NotImplementedError):
        await repo.create("s")


def test_session_repo_helpers():
    content = SessionRepo._message_content(UserMessage(content="안녕"))
    assert content["role"] == "user" and content["content"] == "안녕"
    assert SessionRepo._new_id() != SessionRepo._new_id()
    assert SessionRepo._now_ms() > 0
