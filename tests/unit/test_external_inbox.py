"""external 기능의 inbox: 한 번만 꺼내지는 큐와 넘침 처리를 검증한다."""

from jarvis.core.external import ExternalEventInbox
from tests.fixtures.external_helpers import event


def test_drain_returns_events_only_once() -> None:
    inbox = ExternalEventInbox()
    inbox.put([event("s", "s:1"), event("s", "s:2")])

    assert len(inbox.drain()) == 2
    assert inbox.drain() == []


def test_drain_with_limit_keeps_remainder() -> None:
    inbox = ExternalEventInbox()
    inbox.put([event("s", f"s:{i}") for i in range(5)])

    drained = inbox.drain(limit=2)

    assert len(drained) == 2
    assert len(inbox) == 3


def test_put_counts_dropped_events_on_overflow() -> None:
    inbox = ExternalEventInbox(maxlen=2)

    dropped = inbox.put([event("s", f"s:{i}") for i in range(5)])

    assert dropped == 3
    assert inbox.dropped == 3
    assert len(inbox.drain()) == 2
