"""WakeDetector: 프레임 경계와 무시 구간을 지켜, 이름을 한 번 부르면 한 번만 깨어난다."""

import pytest
from pathlib import Path

from jarvis.voice.wake import (
    FRAME_BYTES,
    REFRACTORY_FRAMES,
    WAKE_MODEL_FILES,
    WakeDetector,
    missing_wake_files,
    openwakeword_scorer,
)

MODELS_DIR = Path(__file__).resolve().parents[3] / "models" / "wakeword"


def scripted(scores: list[float]):
    """프레임마다 정해 둔 점수를 차례로 낸다. 몇 번 불렸는지 센다."""
    calls: list[bytes] = []

    def score(frame: bytes) -> float:
        calls.append(frame)
        return scores[len(calls) - 1]

    return score, calls


def test_frames_split_across_feeds_are_scored_once_whole():
    score, calls = scripted([0.0, 0.0])
    detector = WakeDetector(score, threshold=0.5)

    assert detector.feed(b"\x00" * (FRAME_BYTES - 10)) is None
    assert calls == []
    assert detector.feed(b"\x00" * (FRAME_BYTES + 10)) is None

    assert [len(c) for c in calls] == [FRAME_BYTES, FRAME_BYTES]


def test_wakes_on_first_frame_over_threshold_and_ignores_the_tail():
    tail = [0.9] * REFRACTORY_FRAMES
    score, calls = scripted([0.1, 0.8, *tail, 0.7])
    detector = WakeDetector(score, threshold=0.5)

    assert detector.feed(b"\x00" * FRAME_BYTES * 2) == 0.8
    # 이름 끝의 높은 점수들은 무시하지만 모델 버퍼를 위해 점수는 계속 매긴다
    assert detector.feed(b"\x00" * FRAME_BYTES * REFRACTORY_FRAMES) is None
    assert len(calls) == 2 + REFRACTORY_FRAMES
    # 무시 구간이 지나면 다시 깰 수 있다
    assert detector.feed(b"\x00" * FRAME_BYTES) == 0.7


def test_below_threshold_never_wakes():
    score, _ = scripted([0.49] * 5)
    detector = WakeDetector(score, threshold=0.5)

    assert detector.feed(b"\x00" * FRAME_BYTES * 5) is None


def test_missing_files_are_named(tmp_path):
    (tmp_path / WAKE_MODEL_FILES[0]).write_bytes(b"x")

    assert missing_wake_files(str(tmp_path)) == list(WAKE_MODEL_FILES[1:])


@pytest.mark.skipif(missing_wake_files(str(MODELS_DIR)) != [], reason="models/wakeword 가 없다")
def test_real_model_scores_silence_low():
    pytest.importorskip("openwakeword")
    detector = WakeDetector(openwakeword_scorer(str(MODELS_DIR)), threshold=0.5)

    assert detector.feed(b"\x00" * FRAME_BYTES * 25) is None
