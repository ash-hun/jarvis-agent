"""external 기능의 inbox: 한 번만 꺼내지는 큐, 되돌리기, 넘침 처리를 검증한다."""

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


def test_put_back_returns_events_ahead_of_newer_ones() -> None:
    inbox = ExternalEventInbox()
    inbox.put([event("s", "s:1"), event("s", "s:2")])
    taken = inbox.drain()
    inbox.put([event("s", "s:3")])

    assert inbox.put_back(taken) == 0
    assert [e.key for e in inbox.drain()] == ["s:1", "s:2", "s:3"]


def test_put_back_drops_the_returned_oldest_on_overflow() -> None:
    inbox = ExternalEventInbox(maxlen=2)
    taken = [event("s", "s:1"), event("s", "s:2")]
    inbox.put([event("s", "s:3")])

    assert inbox.put_back(taken) == 1
    assert inbox.dropped == 1
    assert [e.key for e in inbox.drain()] == ["s:2", "s:3"]
