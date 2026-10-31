"""notify 기능: Web Push 구독 API 가 endpoint 를 자연 키로 upsert 하고, 저장소가 없으면 꺼져 있음을 검증한다."""

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.web_hud_helpers import web_assembly, web_client  # noqa: E402

SUBSCRIPTION = {
    "endpoint": "https://web.push.apple.com/x", "expirationTime": None, "keys": {"p256dh": "p", "auth": "a"}
}


class MemoryPushStore:
    def __init__(self) -> None:
        self.rows: dict[str, tuple] = {}

    async def upsert(self, sub, user_id):
        self.rows[sub.endpoint] = (sub.p256dh, sub.auth, user_id)

    async def delete(self, endpoint):
        self.rows.pop(endpoint, None)


def test_push_subscription_upserts_by_endpoint_and_unsubscribes(monkeypatch, tmp_path):
    assembly = web_assembly(monkeypatch, tmp_path, NOTIFY__WEBPUSH_VAPID_PUBLIC_KEY="BPUBLIC")
    store = MemoryPushStore()
    assembly.ctx.push_store = store

    with web_client(assembly) as client:
        vapid = client.get("/api/push/vapid").json()
        subscribed = [client.put("/api/push/subscriptions", json=SUBSCRIPTION).json() for _ in range(2)]
        rows_after_subscribe = len(store.rows)
        missing = client.request("DELETE", "/api/push/subscriptions", json={"endpoint": "https://none"})
        removed = client.request("DELETE", "/api/push/subscriptions", json={"endpoint": SUBSCRIPTION["endpoint"]})

    assert vapid == {"public_key": "BPUBLIC"}
    assert subscribed == [{"ok": True}, {"ok": True}]
    assert rows_after_subscribe == 1
    assert missing.status_code == 200
    assert removed.json() == {"ok": True}
    assert store.rows == {}


def test_push_api_refuses_without_store_or_with_insecure_endpoint(monkeypatch, tmp_path):
    with web_client(web_assembly(monkeypatch, tmp_path)) as client:
        off = client.get("/api/push/vapid")
    assembly = web_assembly(monkeypatch, tmp_path, NOTIFY__WEBPUSH_VAPID_PUBLIC_KEY="BPUBLIC")
    assembly.ctx.push_store = MemoryPushStore()

    with web_client(assembly) as client:
        insecure = client.put("/api/push/subscriptions", json={**SUBSCRIPTION, "endpoint": "http://x"})

    assert off.status_code == 404
    assert insecure.status_code == 400
