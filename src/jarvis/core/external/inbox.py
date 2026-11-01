"""[core] 폴러가 넣고 성찰하는 세션이 한 번에 비우는 앱 레벨 외부 이벤트 큐."""

from collections import deque

from jarvis.core.external.external_types import ExternalEvent
from jarvis.common.logger import get_logger

logger = get_logger(__name__)


class ExternalEventInbox:
    """앱 레벨 단일 큐. 폴러가 넣고, 성찰하는 세션이 한 번에 비운다.

    ExternalTrigger는 "깨우기"만, payload는 이 inbox가 나른다.
    트리거 시그니처와 AnyTrigger race 의미론을 건드리지 않기 위한 분리다.
    drain()이 drain-once이므로 이벤트 1건은 정확히 한 세션에서만 발화된다.
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._events: deque[ExternalEvent] = deque(maxlen=maxlen)
        self._maxlen = maxlen
        self._dropped = 0

    def put(self, events: list[ExternalEvent]) -> int:
        """이벤트를 적재하고 상한 초과로 버려진 건수를 반환(조용한 절단 금지)."""
        overflow = max(0, len(self._events) + len(events) - self._maxlen)
        self._events.extend(events)
        if overflow:
            self._dropped += overflow
            logger.info(
                f"[ExternalEventInbox] maxlen={self._maxlen} 초과 — 오래된 이벤트 "
                f"{overflow}건 드롭 (누적 {self._dropped}건)"
            )
        return overflow

    def put_back(self, events: list[ExternalEvent]) -> int:
        """꺼냈지만 전하지 못한 이벤트를 꺼낸 순서대로 앞에 되돌리고 상한 초과로 버린 건수를 반환.

        되돌린 쪽이 더 오래된 이벤트라 넘치면 그쪽부터 버린다(put 과 같은 규칙).
        """
        # ponytail: 되돌린 이벤트는 전할 때까지 성찰마다 다시 오른다, 오래 남는 이벤트가 보이면 되돌린 횟수에 상한
        merged = [*events, *self._events]
        overflow = max(0, len(merged) - self._maxlen)
        self._events = deque(merged[overflow:], maxlen=self._maxlen)
        if overflow:
            self._dropped += overflow
            logger.info(
                f"[ExternalEventInbox] maxlen={self._maxlen} 초과, 되돌린 이벤트 {overflow}건 드롭"
                f" (누적 {self._dropped}건)"
            )
        return overflow

    def drain(self, limit: int | None = None) -> list[ExternalEvent]:
        """적재된 이벤트를 꺼내 비운다. 두 번째 호출은 빈 목록(발화 1회 보장)."""
        if limit is None or limit >= len(self._events):
            drained = list(self._events)
            self._events.clear()
            return drained
        return [self._events.popleft() for _ in range(max(0, limit))]

    @property
    def dropped(self) -> int:
        return self._dropped

    def __len__(self) -> int:
        return len(self._events)
