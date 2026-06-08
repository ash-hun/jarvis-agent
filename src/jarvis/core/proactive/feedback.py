from __future__ import annotations


class FeedbackLearner:
    """proactive 발화 수락/무시를 누적해 confidence 임계치를 자동 조정한다 (C3).

    - 수락(accepted) → 임계치 ↓ (더 적극적으로 말함)
    - 무시(dismissed) → 임계치 ↑ (더 보수적으로 침묵)
    경계 [min, max] 안에서 단조 조정. 순수 로직(독립 class)이라 단위 테스트 용이.
    정책은 threshold()를 동적 임계치로 사용한다.
    """

    def __init__(
        self,
        base_threshold: float = 0.6,
        *,
        min_threshold: float = 0.3,
        max_threshold: float = 0.95,
        step: float = 0.05,
    ) -> None:
        self._threshold = _clamp(base_threshold, min_threshold, max_threshold)
        self._min = min_threshold
        self._max = max_threshold
        self._step = step
        self._accepts = 0
        self._dismisses = 0

    def threshold(self) -> float:
        return self._threshold

    def record(self, accepted: bool) -> None:
        if accepted:
            self._accepts += 1
            self._threshold = _clamp(self._threshold - self._step, self._min, self._max)
        else:
            self._dismisses += 1
            self._threshold = _clamp(self._threshold + self._step, self._min, self._max)

    def stats(self) -> dict[str, float | int]:
        return {
            "threshold": self._threshold,
            "accepts": self._accepts,
            "dismisses": self._dismisses,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
