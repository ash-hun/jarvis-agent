"""memory_eval 기능의 naive RAG 비교군: 턴 묶기, 긴 턴 창, 코사인 top-k."""

from jarvis.memory.eval.rag_baseline import CHUNK_CHARS, WINDOW_CHARS, RagIndex, chunk_sessions
from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkSession, BenchmarkTurn
from jarvis.memory.eval.fake_embedder import FakeEmbedder


def _session(sid: str, texts: list[str], date: str = "2023/05/20") -> BenchmarkSession:
    turns = [BenchmarkTurn(role="user", text=t, turn_id=f"{sid}#{i}") for i, t in enumerate(texts)]
    return BenchmarkSession(session_id=sid, date=date, turns=turns)


def test_short_turns_merge_with_overlap_and_never_cross_sessions():
    chunks = chunk_sessions([_session("a", ["x" * 400] * 3), _session("b", ["y" * 10])])

    assert [c.turn_ids for c in chunks] == [("a#0", "a#1"), ("a#1", "a#2"), ("b#0",)]
    assert all(c.text.startswith("[2023/05/20]\n") for c in chunks)
    assert all(len(c.text) <= CHUNK_CHARS + len("[2023/05/20]\n") + 1 for c in chunks)


def test_very_long_turn_is_split_into_overlapping_windows():
    chunks = chunk_sessions([_session("a", ["z" * (WINDOW_CHARS + 2000)], date="")])

    assert len(chunks) == 2 and all(c.turn_ids == ("a#0",) for c in chunks)
    assert len(chunks[0].text) == WINDOW_CHARS


async def test_search_returns_closest_chunks_first_and_empty_for_blank_query():
    question = BenchmarkQuestion("q", "t", "거주지 어디", "부산",
                                 [_session("a", ["거주지: 부산"]), _session("b", ["점심 메뉴 김밥"])])
    index = RagIndex(FakeEmbedder())
    await index.ingest(question)

    assert (await index.search("거주지", 1))[0].session_id == "a"
    assert await index.search("   ", 3) == []
