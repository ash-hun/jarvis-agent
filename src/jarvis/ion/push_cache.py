"""[ion] 푸시 구독을 Postgres 에서 파일로 복사해 둔다. DB 가 죽어도 알림은 나간다."""

import json
from pathlib import Path
from typing import Protocol
from collections.abc import Iterable

from jarvis.core.notify.webpush import Subscription


class SubscriptionSource(Protocol):
    async def all(self) -> list[Subscription]: ...


class FilePushStore:
    """구독 목록 JSON 파일. endpoint 가 키라 같은 목록을 두 번 써도 같다."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def all(self) -> list[Subscription]:
        if not self._path.exists():
            return []
        rows = json.loads(self._path.read_text(encoding="utf-8") or "[]")
        return [Subscription(r["endpoint"], r["p256dh"], r["auth"]) for r in rows]

    def replace(self, subs: Iterable[Subscription]) -> bool:
        """목록을 통째로 바꾼다. 내용이 같으면 쓰지 않고 False."""
        new = sorted({s.endpoint: s for s in subs}.values(), key=lambda s: s.endpoint)
        if new == self.all():
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth} for s in new]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return True

    def delete(self, endpoint: str) -> None:
        self.replace(s for s in self.all() if s.endpoint != endpoint)


async def sync_subscriptions(source: SubscriptionSource, target: FilePushStore) -> int:
    """원본의 구독을 파일로 복사한다. 돌려주는 값은 복사한 구독 수. 두 번 돌려도 파일은 같다."""
    subs = await source.all()
    target.replace(subs)
    return len(subs)
