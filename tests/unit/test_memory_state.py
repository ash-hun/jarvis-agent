"""memory 기능의 작업 기억 상태와 저장소: 메모 상한, 되뇌기 수, 저장소의 왕복, 세션 격리, 사본 반환."""

import pytest

from jarvis.memory.working.state import MAX_NOTES, WorkingState, WorkingStore
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.working.postgres import PostgresWorkingStore
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


@pytest.mark.parametrize(
    "store",
    [InMemoryWorkingStore(), PostgresWorkingStore(dsn="postgresql://unused")],
    ids=["in_memory", "postgres_not_connected"],
)
def test_concrete_working_stores_inherit_the_base(store):
    assert isinstance(store, WorkingStore)


def test_working_state_notes_are_capped_and_rehearsal_counts():
    state = WorkingState(scope=SCOPE)

    for i in range(MAX_NOTES + 5):
        state.add_note(f"n{i}")

    assert len(state.notes) == MAX_NOTES and state.notes[0] == "n5"
    assert [state.rehearse("a"), state.rehearse("a"), state.rehearse("b")] == [1, 2, 1]


async def test_working_store_base_roundtrip_and_legacy_defaults():
    store = WorkingStore()
    await store.save(WorkingState(scope=SCOPE, rehearsal={"i": 2}, notes=["n"]))

    loaded = await store.load(SCOPE)

    assert (loaded.rehearsal, loaded.notes) == ({"i": 2}, ["n"])
    await store.clear(SCOPE)
    assert (await store.load(SCOPE)).notes == []
    assert await store.legacy_stm_rows() is None
    await store.drop_legacy_stm()


async def test_in_memory_working_store_roundtrip_and_session_isolation():
    store = InMemoryWorkingStore()
    assert (await store.load(SCOPE)).notes == [] and (await store.load(SCOPE)).rehearsal == {}
    state = WorkingState(scope=SCOPE)
    state.add_note("n1")
    state.rehearse("item")
    state.rehearse("item")

    await store.save(state)

    assert ((await store.load(SCOPE)).notes, (await store.load(SCOPE)).rehearsal) == (["n1"], {"item": 2})
    assert (await store.load(SCOPE.with_session("s2"))).notes == []
    await store.clear(SCOPE)
    assert (await store.load(SCOPE)).notes == []


async def test_in_memory_working_store_hands_out_copies():
    store = InMemoryWorkingStore()
    state = WorkingState(scope=SCOPE)
    state.add_note("first")
    await store.save(state)

    state.add_note("after save")
    loaded = await store.load(SCOPE)
    loaded.rehearse("x")
    loaded.notes.append("x")

    again = await store.load(SCOPE)
    assert again.notes == ["first"] and again.rehearsal == {}
