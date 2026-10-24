"""[core] 앱(iOS 홈 화면 웹앱)의 Web Push 구독을 Postgres 에 두고, 알림 payload 를 구독 전부에 보낸다."""

import json
import asyncio
from typing import Any
from functools import partial
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from jarvis.core.notify.webhook import headline
from jarvis.common.logger import get_logger

# iOS 가 보여 주는 길이는 이보다 짧다. 암호화한 본문이 4KB 를 넘지 않게 자른다
BODY_MAX = 1000
# 푸시 서비스가 이 상태를 주면 구독이 죽은 것이다(앱 삭제, 알림 끔). 지운다
GONE_STATUSES = frozenset({404, 410})
# 기기가 꺼져 있을 때 푸시 서비스가 들고 있는 시간(초). 하루가 지난 알림은 버린다
TTL_SEC = 86400
DEFAULT_TITLE = "JARVIS"

Notify = Callable[[dict[str, Any]], Awaitable[None]]
# (구독, 본문 JSON) -> 푸시 서비스의 HTTP 상태. 기본은 pywebpush. 테스트는 가짜를 넣는다
Send = Callable[["Subscription", str], Awaitable[int]]

logger = get_logger(__name__)


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str

    def info(self) -> dict[str, Any]:
        """pywebpush 가 받는 PushSubscription 모양."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def push_body(payload: dict[str, Any]) -> dict[str, str] | None:
    """service worker 가 받는 {title, body, tag}. 보일 글이 없으면 None(빈 푸시는 iOS 가 구독을 끊는다). 순수 함수."""
    title, body = headline(payload)
    if not title.strip() and not body.strip():
        return None
    tag = str(payload.get("id") or payload.get("message_id") or "")
    return {"title": title.strip() or DEFAULT_TITLE, "body": body[:BODY_MAX], "tag": tag}


def is_gone(status: int) -> bool:
    return status in GONE_STATUSES


def validate_subscription(data: dict[str, Any]) -> Subscription:
    """브라우저 PushSubscription.toJSON(). https endpoint 와 두 키가 없으면 ValueError."""
    endpoint = str(data.get("endpoint") or "")
    keys = data.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    if not endpoint.startswith("https://"):
        raise ValueError("endpoint must start with https://")
    if not p256dh or not auth:
        raise ValueError("keys.p256dh and keys.auth are required")
    return Subscription(endpoint, p256dh, auth)


class PushStore:
    """구독은 endpoint 가 자연 키다. 같은 기기가 몇 번 구독해도 행은 하나다."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        # asyncpg 는 타입 스텁이 없어 풀을 Any 로 다룬다
        self._pool: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _get_pool(self) -> Any:
        import asyncpg

        loop = asyncio.get_running_loop()
        if self._pool is None or self._loop is not loop:
            self._pool = await asyncpg.create_pool(self._dsn)
            self._loop = loop
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS push_subscriptions (
                        endpoint   text PRIMARY KEY,
                        p256dh     text NOT NULL,
                        auth       text NOT NULL,
                        user_id    text,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                """)
        return self._pool

    async def upsert(self, sub: Subscription, user_id: str | None) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_id) VALUES ($1, $2, $3, $4)"
                " ON CONFLICT (endpoint) DO UPDATE SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth,"
                " user_id = EXCLUDED.user_id, updated_at = now()",
                sub.endpoint, sub.p256dh, sub.auth, user_id,
            )

    async def delete(self, endpoint: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM push_subscriptions WHERE endpoint = $1", endpoint)

    async def all(self) -> list[Subscription]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        return [Subscription(r["endpoint"], r["p256dh"], r["auth"]) for r in rows]


def pywebpush_sender(private_key: str, subject: str) -> Send:
    """VAPID 로 서명하고 aes128gcm 으로 암호화해 보낸다. 실패한 응답의 상태를 돌려준다."""

    def send_sync(sub: Subscription, data: str) -> int:
        from pywebpush import WebPushException, webpush

        try:
            response = webpush(
                sub.info(), data, vapid_private_key=private_key, vapid_claims={"sub": subject}, ttl=TTL_SEC,
            )
        except WebPushException as exc:
            return int(exc.response.status_code) if exc.response is not None else 0
        except Exception as exc:  # 네트워크 오류 등. 한 구독의 실패가 다른 구독 발송을 막지 않게
            logger.info(f"[Notify] web push send failed: {exc!r}")
            return 0
        return int(getattr(response, "status_code", 201))

    async def send(sub: Subscription, data: str) -> int:
        return await asyncio.get_running_loop().run_in_executor(None, partial(send_sync, sub, data))

    return send


def webpush_notifier(store: PushStore, send: Send) -> Notify:
    """# idempotent: 푸시에는 중복 제거 키가 없다, 재시도하지 않고 tag 로 같은 알림을 덮어 하나로 보인다

    구독 전부에 보낸다. 404, 410 이면 그 구독을 지우고, 그 밖의 실패는 로그만 남긴다.
    """

    async def notify(payload: dict[str, Any]) -> None:
        body = push_body(payload)
        if body is None:
            return
        data = json.dumps(body, ensure_ascii=False)
        for sub in await store.all():
            status = await send(sub, data)
            if is_gone(status):
                await store.delete(sub.endpoint)
                logger.info(f"[Notify] web push subscription gone ({status}), removed")
            elif status >= 400 or status == 0:
                logger.info(f"[Notify] web push returned {status}")

    return notify
