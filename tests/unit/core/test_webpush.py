"""Web Push: 알림 payload 를 {title, body, tag} 로 바꾸고, 구독 전부에 보내고, 죽은 구독은 지운다."""

import json
import pytest
import asyncio

from jarvis.core.notify.webpush import BODY_MAX, Subscription, is_gone, push_body, validate_subscription
from jarvis.core.notify.webpush import webpush_notifier

ALIVE = Subscription("https://web.push.apple.com/alive", "p", "a")
DEAD = Subscription("https://web.push.apple.com/dead", "p", "a")


class Store:
    def __init__(self, subs: list[Subscription]) -> None:
        self.subs = {s.endpoint: s for s in subs}

    async def all(self):
        return list(self.subs.values())

    async def delete(self, endpoint):
        self.subs.pop(endpoint, None)


def test_body_uses_the_headline_and_the_id_as_tag():
    body = push_body({"type": "reminder", "kind": "reminder", "label": "아침 날씨", "text": "맑음, 18도", "id": "r1"})
    assert body == {"title": "⏰ 아침 날씨", "body": "맑음, 18도", "tag": "r1"}
    long = {"type": "proactive_message", "agent_name": "K.A.R.E.N.", "text": "x" * 5000, "message_id": "m"}
    proactive = push_body(long)
    assert proactive is not None and len(proactive["body"]) == BODY_MAX and proactive["tag"] == "m"


def test_gone_and_validation():
    assert is_gone(404) and is_gone(410) and not is_gone(201) and not is_gone(429)
    sub = validate_subscription({"endpoint": "https://e", "expirationTime": None, "keys": {"p256dh": "p", "auth": "a"}})
    assert sub == Subscription("https://e", "p", "a")
    for bad in ({"endpoint": "http://e", "keys": {"p256dh": "p", "auth": "a"}}, {"endpoint": "https://e", "keys": {}}):
        with pytest.raises(ValueError):
            validate_subscription(bad)


def test_sends_to_every_subscription_and_drops_the_dead_one():
    store = Store([ALIVE, DEAD])
    sent: list[tuple[str, dict]] = []

    async def send(sub, data):
        sent.append((sub.endpoint, json.loads(data)))
        return 410 if sub is DEAD else 201

    asyncio.run(webpush_notifier(store, send)({"type": "reminder", "label": "알림", "text": "회의 10분 전", "id": "r"}))
    assert {e for e, _ in sent} == {ALIVE.endpoint, DEAD.endpoint}
    assert sent[0][1]["body"] == "회의 10분 전"
    assert list(store.subs) == [ALIVE.endpoint]
