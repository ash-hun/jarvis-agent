"""memory 기능의 기억 항목 모델: 기본값, 항목끼리 가변 기본값을 공유하지 않음, 기억 종류."""

from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def test_memory_item_defaults_and_session_property():
    a = MemoryItem(content="x", kind=MemoryKind.EPISODIC, scope=SCOPE)
    b = MemoryItem(content="x", kind=MemoryKind.EPISODIC, scope=SCOPE)

    a.tags.append("t")
    a.metadata["k"] = 1

    assert a.id != b.id and len(a.id) == 32
    assert (a.author, a.importance, a.rehearsal_count) == ("agent", 0.5, 0)
    assert a.session_id == "s1"
    assert b.tags == [] and b.metadata == {}


def test_memory_kind_values():
    assert {k.value for k in MemoryKind} == {"episodic", "semantic", "procedural"}
