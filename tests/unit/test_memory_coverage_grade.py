"""memory: 회상 항목이 질문의 대상을 덮는지 가리고 빠진 대상의 항목을 같은 개수 안에 섞는지 검증."""

from jarvis.memory.retrieval.coverage_grade import merge_coverage, uncovered
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope

SCOPE = MemoryScope(user_id="u1", agent_id="main")


def _item(content: str, embedding: list[float] | None = None) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.EPISODIC, scope=SCOPE, embedding=embedding)


def test_uncovered_keeps_names_missing_by_text_and_vector():
    items = [_item("Went hiking with Emma on Sunday", [1.0, 0.0])]
    names = ["emma", "dentist", "trail walk"]

    assert uncovered(names, items, [None, [0.0, 1.0], [0.9, 0.1]]) == ["dentist"]


def test_uncovered_without_items_or_vectors_returns_every_name():
    assert uncovered(["Emma", "dentist"], []) == ["Emma", "dentist"]


def test_merge_coverage_replaces_tail_and_keeps_first_rank():
    first = [_item("a"), _item("b"), _item("c")]
    extra = [_item("x"), first[0]]

    merged = merge_coverage(first, extra, 3)

    assert [i.content for i in merged] == ["a", "b", "x"]


def test_merge_coverage_never_drops_the_top_first_item():
    first = [_item("a"), _item("b")]
    extra = [_item("x"), _item("y"), _item("z")]

    assert [i.content for i in merge_coverage(first, extra, 2)] == ["a", "x"]
