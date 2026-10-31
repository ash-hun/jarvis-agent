"""openloop: 메모리 저장소의 저장, 같은 약속 합치기(글자, 임베딩), 상태 변경, 만료 닫기를 검증한다."""

import pytest

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop, OpenLoopStore, close_expired
from jarvis.model_layer.embeddings import Embedder


class _TableEmbedder(Embedder):
    """문구별로 정해 둔 벡터를 돌려준다. 표에 없는 문구는 서로 직교하는 축에 놓는다."""

    model = "table"
    dimensions = 3

    def __init__(self, table: dict[str, list[float]], fail: bool = False) -> None:
        self.table = table
        self.fail = fail
        self.calls = 0
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += texts
        if self.fail:
            raise ConnectionError("ollama down")
        return [self.table.get(t, [0.0, 0.0, 1.0]) for t in texts]


def _loop(desc, *, due=None, session="s1"):
    return OpenLoop(description=desc, due_ms=due, origin_session=session)


def test_in_memory_store_is_open_loop_store():
    assert isinstance(InMemoryOpenLoopStore(), OpenLoopStore)


async def test_add_then_get_returns_open_loop():
    store = InMemoryOpenLoopStore()

    lid = await store.add(OpenLoop(description="배포 결과 공유", origin_session="s1"))
    got = await store.get(lid)

    assert got is not None and got.description == "배포 결과 공유"
    assert got.status == "open"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("배포  결과 공유", "배포 결과 공유"),
        ("내일 배포 전에 로그 확인해줘", "로그 확인해줘"),
        (None, "   "),
    ],
)
async def test_add_unique_skips_duplicate_or_blank_in_same_session(first, second):
    store = InMemoryOpenLoopStore()
    if first is not None:
        assert await store.add_unique(_loop(first))

    dup = await store.add_unique(_loop(second))

    assert dup is None
    assert len(await store.all()) == (0 if first is None else 1)


async def test_add_unique_keeps_other_session_and_other_description():
    store = InMemoryOpenLoopStore()
    await store.add_unique(_loop("A 작업"))

    other_session = await store.add_unique(_loop("A 작업", session="s2"))
    other_desc = await store.add_unique(_loop("B 작업"))

    assert other_session is not None
    assert other_desc is not None
    assert len(await store.all()) == 3


async def test_add_unique_updates_paraphrase_due_instead_of_adding():
    store = InMemoryOpenLoopStore()
    first = await store.add_unique(_loop("내일 오전 10시 팀 배포 결과 공유 회의 준비 및 진행"))

    paraphrase = _loop("내일 오전 10시 팀 배포 결과 공유 회의 준비 및 핵심 메시지 구조화 완료", due=5000)
    again = await store.add_unique(paraphrase)

    loops = await store.list_open()
    assert again == first
    assert len(loops) == 1 and loops[0].due_ms == 5000


async def test_add_unique_merges_paraphrase_by_embedding_and_reruns_idempotent():
    embedder = _TableEmbedder(
        {"참석자 목록 확정": [1.0, 0.0, 0.0], "회의 참석자들의 최종 리스트 확정": [0.95, 0.31, 0.0]}
    )
    store = InMemoryOpenLoopStore(embedder)
    first = await store.add_unique(_loop("참석자 목록 확정"))

    assert await store.add_unique(_loop("회의 참석자들의 최종 리스트 확정")) is None
    assert await store.add_unique(_loop("회의 참석자들의 최종 리스트 확정")) is None
    assert [x.id for x in await store.list_open()] == [first]
    assert await store.add_unique(_loop("원하는 알림 주기 확정"))
    assert len(await store.list_open()) == 2


async def test_add_unique_embeds_each_open_loop_once():
    embedder = _TableEmbedder({})
    store = InMemoryOpenLoopStore(embedder)
    texts = ["참석자 목록 확정", "배포 결과 공유", "알림 주기 확정", "회의록 정리"]

    for text in texts:
        await store.add_unique(_loop(text))

    assert sorted(embedder.texts) == sorted(texts)


async def test_add_unique_falls_back_to_text_when_embedding_fails():
    embedder = _TableEmbedder({}, fail=True)
    store = InMemoryOpenLoopStore(embedder)

    assert await store.add_unique(_loop("참석자 목록 확정"))
    assert await store.add_unique(_loop("참석자 목록 확정")) is None
    assert await store.add_unique(_loop("회의 참석자들의 최종 리스트 확정"))
    assert embedder.calls == 2  # 첫 약속은 비교할 후보가 없어 임베딩을 부르지 않는다


async def test_list_open_filters_status_and_session():
    store = InMemoryOpenLoopStore()
    a = await store.add(_loop("열림1"))
    await store.add(_loop("열림2", session="s2"))
    done = await store.add(_loop("완료됨"))
    await store.update_status(done, "done")

    s1_open = await store.list_open(session_id="s1")
    all_open = await store.list_open()

    assert [x.id for x in s1_open] == [a]
    assert len(all_open) == 2


async def test_update_status_rejects_unknown_status_and_id():
    store = InMemoryOpenLoopStore()
    lid = await store.add(OpenLoop(description="x"))

    assert await store.update_status(lid, "done") is True
    assert (await store.get(lid)).status == "done"
    assert await store.update_status(lid, "bogus") is False
    assert await store.update_status("nonexistent", "done") is False


async def test_close_expired_twice_is_same():
    store = InMemoryOpenLoopStore()
    loop_id = await store.add(_loop("기한 지남", due=1_000))

    first = await close_expired(store, now_ms=10_000, grace_ms=0, max_age_ms=0)
    second = await close_expired(store, now_ms=10_000, grace_ms=0, max_age_ms=0)

    assert first == [loop_id]
    assert second == []
    assert (await store.get(loop_id)).status == "expired"
