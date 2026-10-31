"""session 의 Web SessionRegistry: 종료 때 세션마다 공고화, 삭제 순서, 스케줄 결과를 건넬 세션 고르기를 검증한다."""

import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from jarvis.ui.web.session_registry import SessionRegistry, last_conversation
from jarvis.agent_layer.session.session_protocol import SessionMetadata
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.jarvis_config import JarvisSettings
from jarvis.memory import MemoryScope


class _Agents:
    main = SimpleNamespace(agent_id="main")

    def __init__(self, sessions: dict[str, MagicMock]) -> None:
        self._sessions = sessions

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in ("main", "karen")

    def approval_rules(self, agent_id: str) -> list:
        return []

    def builder(self, agent_id: str) -> SimpleNamespace:
        def build(session_id: str, services, inherit_scope: bool = False) -> MagicMock:  # type: ignore[no-untyped-def]
            return self._sessions.setdefault(session_id, _mock_session(session_id))

        return SimpleNamespace(build=build)


def _mock_session(session_id: str, scope: MemoryScope | None = None) -> MagicMock:
    s = MagicMock()
    s.settle = AsyncMock()
    s.memory_scope = scope or MemoryScope(user_id="local", session_id=session_id)
    return s


def _repo(metas: list[SessionMetadata] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_meta = AsyncMock(return_value=None)
    repo.delete = AsyncMock()
    repo.list = AsyncMock(return_value=metas or [])
    return repo


def _registry(
    repo: MagicMock | None = None, sessions: dict[str, MagicMock] | None = None, services: MagicMock | None = None
) -> SessionRegistry:
    services = services or MagicMock()
    services.with_security = lambda pipeline, sandbox: services
    ctx = SimpleNamespace(settings=JarvisSettings(), session_repo=repo or _repo())
    return SessionRegistry(ctx, services, _Agents(sessions if sessions is not None else {}))  # type: ignore[arg-type]


def _meta(sid: str, agent: str, updated: int, count: int = 4) -> SessionMetadata:
    return SessionMetadata(session_id=sid, cwd=".", created_at=0, updated_at=updated, message_count=count,
                           agent_id=agent)


async def test_shutdown_consolidates_every_session_in_its_own_scope():
    """종료 때 대화를 다시 요약하지 않는다(턴마다 EDM 에 남았다). 세션마다 공고화만 돈다."""
    from jarvis.memory.consolidation.semantic_extract import Fact

    async def extractor(text: str) -> list[Fact]:
        return [Fact("거주지", "부산", 0.9)]

    ltm = MemoryService(InMemoryItemStore(), extractor=extractor)
    jh = MemoryScope(user_id="jh", session_id="s")
    await ltm.record_turn(1, "부산으로 이사했어", "축하해요", jh)
    session = _mock_session("s", jh)
    registry = _registry(sessions={"s": session})
    await registry.get_or_create("s")

    await registry.consolidate_all_sessions(ltm)

    # 사용자 프로필은 모든 에이전트가 본다
    facts = await ltm.fixed_facts(MemoryScope(user_id="jh", agent_id="researcher"))
    assert [f.content for f in facts] == ["거주지: 부산"]
    assert await ltm.fixed_facts(MemoryScope(user_id="other")) == []
    session.settle.assert_awaited_once()


async def test_consolidate_one_failing_session_does_not_stop_the_others():
    crash, ok = _mock_session("crash"), _mock_session("ok")
    crash.settle = AsyncMock(side_effect=RuntimeError("boom"))
    registry = _registry(sessions={"crash": crash, "ok": ok})
    await registry.get_or_create("crash")
    await registry.get_or_create("ok")

    await registry.consolidate_all_sessions(MemoryService(InMemoryItemStore()))

    ok.settle.assert_awaited_once()


async def test_remove_forgets_the_sessions_memory_before_its_history():
    order: list[str] = []
    repo = _repo()
    repo.delete = AsyncMock(side_effect=lambda sid: order.append(f"repo:{sid}"))
    services = MagicMock()
    services.memory.forget_session = AsyncMock(side_effect=lambda sid: order.append(f"memory:{sid}"))
    registry = _registry(repo, services=services)
    await registry.get_or_create("s")

    await registry.remove("s")
    await registry.remove("s")

    assert order == ["memory:s", "repo:s", "memory:s", "repo:s"]
    assert "s" not in registry.list_ids()


async def test_latest_of_picks_the_session_the_user_talked_to_most_recently(monkeypatch):
    """스케줄 결과를 건넬 세션. 사용자가 말한 적 없는 세션(위임받은 세션)은 고르지 않는다."""
    # touch 는 monotonic 시각이라 연달아 부르면 같을 수 있다. 시각을 차례로 늘려 준다
    ticks = itertools.count(1.0)
    monkeypatch.setattr("jarvis.ui.web.session_registry.time.monotonic", lambda: next(ticks))
    registry = _registry()
    for sid, agent in (("k1", "karen"), ("k2", "karen"), ("peer", "karen"), ("j", "main")):
        await registry.get_or_create(sid, agent)
    assert registry.latest_of("karen") is None

    for sid in ("k2", "j", "k1"):
        registry.touch(sid)
    assert registry.latest_of("karen") is (await registry.get_or_create("k1"))[0]
    registry.touch("k2")

    assert registry.latest_of("karen") is (await registry.get_or_create("k2"))[0]
    assert registry.latest_of("main") is (await registry.get_or_create("j"))[0]


def test_last_conversation_is_the_latest_saved_talk_not_a_run_or_test():
    """재시작 뒤 건넬 세션: 그 에이전트와 사용자가 나눈 마지막 대화. 스케줄 실행, 위임, 시험, 빈 세션은 뺀다."""
    metas = [
        _meta("a1b2c3d4", "karen", 10), _meta("e5f6a7b8", "karen", 20), _meta("e0e0e0e0", "karen", 90, count=0),
        _meta("sched-goal-x-1", "karen", 99), _meta("peer-main-karen", "karen", 98),
        _meta("live-goal-nl-1", "karen", 97),
        _meta("test-x", "karen", 96), _meta("j1j1j1j1", "main", 95),
    ]

    assert last_conversation(metas, "karen") == "e5f6a7b8"
    assert last_conversation(metas, "main") == "j1j1j1j1"
    assert last_conversation(metas, "ghost") is None


async def test_conversation_of_reopens_the_saved_talk_and_creates_one_only_when_none():
    """열린 대화가 없으면 저장된 마지막 대화를 열고, 그것도 없으면 새로 만든다. 다시 불러도 같은 세션이다."""
    repo = _repo([_meta("a1b2c3d4", "karen", 10)])
    registry = _registry(repo)

    first = await registry.conversation_of("karen")
    again = await registry.conversation_of("karen")

    assert first is again
    assert registry.list_ids() == ["a1b2c3d4"]

    fresh = _registry(_repo([]))
    await fresh.conversation_of("karen")

    [created] = fresh.list_ids()
    assert created != "a1b2c3d4" and fresh.agent_of(created) == "karen"
