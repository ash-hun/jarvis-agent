"""infra 의 구독 캐시: 같은 목록을 두 번 써도 파일은 같고, 원본에서 복사해 와도 같다."""

from jarvis.infra.push_cache import FilePushStore, sync_subscriptions
from jarvis.core.notify.webpush import Subscription

A = Subscription("https://p/a", "k1", "a1")
B = Subscription("https://p/b", "k2", "a2")


def test_replace_is_idempotent_and_delete_removes_one(tmp_path):
    store = FilePushStore(tmp_path / "infra" / "subscriptions.json")

    assert store.replace([B, A]) is True
    assert store.replace([A, B]) is False
    assert store.all() == [A, B]
    store.delete(A.endpoint)
    assert store.all() == [B]


async def test_sync_copies_from_the_source_twice_to_the_same_file(tmp_path):
    class Source:
        async def all(self) -> list[Subscription]:
            return [A]

    store = FilePushStore(tmp_path / "subs.json")
    assert await sync_subscriptions(Source(), store) == 1
    first = (tmp_path / "subs.json").read_text()
    assert await sync_subscriptions(Source(), store) == 1
    assert (tmp_path / "subs.json").read_text() == first and store.all() == [A]
