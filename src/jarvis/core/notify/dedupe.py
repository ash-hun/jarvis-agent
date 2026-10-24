"""[core] 같은 말이 잠깐 사이에 여러 번 와도 밖으로는 한 번만 보낸다."""

from collections.abc import Callable, Hashable

# 같은 세션을 연 화면들은 같은 답을 거의 동시에 읽는다. 읽기 대기열이 밀린 화면도 덮을 만큼만 잡는다
SPOKEN_DEDUPE_SEC = 10.0


class RecentOnce:
    """키를 처음 본 뒤 window_sec 동안 같은 키를 거른다. 시계는 경계에서 넣는다."""

    def __init__(self, window_sec: float, clock: Callable[[], float]) -> None:
        self._window_sec = window_sec
        self._clock = clock
        self._seen: dict[Hashable, float] = {}

    def first(self, key: Hashable) -> bool:
        now = self._clock()
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._window_sec}
        if key in self._seen:
            return False
        self._seen[key] = now
        return True
