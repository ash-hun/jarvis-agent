"""thought 의 ThoughtLog 싱크: 장기 기억과 작업 기억 메모에 남기고, 한 싱크의 실패를 격리한다."""

from jarvis.agent_layer.thought import LTMThoughtSink, ThoughtFrame, ThoughtLog, WorkingNotesSink, ThoughtSink
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope


S1 = MemoryScope(user_id="local", session_id="s1")


class BoomSink:
    async def store(self, frame, scope):  # type: ignore[no-untyped-def]
        raise RuntimeError("sink down")


async def test_ltm_sink_persists_full_frame():
    backend = MemoryService(InMemoryItemStore())
    log = ThoughtLog([LTMThoughtSink(backend)])

    await log.store(ThoughtFrame(decision="ask", confidence=0.7, interpretation="x"), S1)

    entries = await backend.recent(S1, limit=10)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == THOUGHT_SOURCE
    assert entry.session_id == "s1"
    assert entry.metadata["decision"] == "ask"
    assert ThoughtFrame.model_validate_json(entry.content).interpretation == "x"


async def test_notes_sink_writes_to_working_memory_not_to_long_term():
    memory = MemoryService(InMemoryItemStore())
    log = ThoughtLog([WorkingNotesSink(memory)])

    await log.store(ThoughtFrame(decision="silent", interpretation="속마음"), S1)

    notes = (await memory.working_state(S1)).notes
    assert len(notes) == 1 and THOUGHT_SOURCE in notes[0] and "속마음" in notes[0]
    assert await memory.recent(S1) == []


async def test_store_fans_out_to_multiple_sinks():
    ltm = MemoryService(InMemoryItemStore())
    log = ThoughtLog([LTMThoughtSink(ltm), WorkingNotesSink(ltm)])

    await log.store(ThoughtFrame(interpretation="y"), S1)

    assert len(await ltm.recent(S1, limit=10)) == 1
    assert len((await ltm.working_state(S1)).notes) == 1


async def test_store_isolates_sink_failure():
    ltm = MemoryService(InMemoryItemStore())
    log = ThoughtLog([BoomSink(), LTMThoughtSink(ltm)])

    await log.store(ThoughtFrame(interpretation="z"), S1)

    assert len(await ltm.recent(S1, limit=10)) == 1


class _ListSink(ThoughtSink):
    def __init__(self) -> None:
        self.frames: list[tuple[ThoughtFrame, str | None]] = []

    async def store(self, frame: ThoughtFrame, session_id: str | None = None) -> None:  # type: ignore[override]
        self.frames.append((frame, session_id))


async def test_thought_sink_base_discards_and_log_nests():
    frame = ThoughtFrame(interpretation="x")
    await ThoughtSink().store(frame, "s")  # type: ignore[arg-type]
    inner = _ListSink()
    outer = ThoughtLog([ThoughtLog([inner]), ThoughtSink()])

    await outer.store(frame, "s")  # type: ignore[arg-type]

    assert isinstance(outer, ThoughtSink)
    assert inner.frames == [(frame, "s")]
