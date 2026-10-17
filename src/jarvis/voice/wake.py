"""[voice] 16kHz PCM 을 80ms 프레임으로 잘라 점수를 매기고 "Jarvis" 를 불렀는지 판정하는 웨이크워드 감지기."""

from collections.abc import Callable
from pathlib import Path

# openWakeWord 의 입력 단위: 16kHz mono int16 1280 샘플(80ms)
FRAME_SAMPLES = 1280
FRAME_BYTES = FRAME_SAMPLES * 2
# 이름 끝 무렵 여러 프레임이 연달아 임계치를 넘는다. 첫 프레임에서 깨고 그 뒤 1초(13프레임)는 무시한다
REFRACTORY_FRAMES = 13
WAKE_MODEL = "jarvis.onnx"
MELSPEC_MODEL = "melspectrogram.onnx"
EMBEDDING_MODEL = "embedding_model.onnx"
WAKE_MODEL_FILES = (WAKE_MODEL, MELSPEC_MODEL, EMBEDDING_MODEL)

# 프레임 하나(FRAME_BYTES 의 int16 LE PCM) → 웨이크워드 점수(0~1)
Scorer = Callable[[bytes], float]


class WakeDetector:
    """연결 하나의 감지 상태. 프레임 경계에 걸친 바이트와 깨어난 뒤 무시할 프레임 수를 들고 있다."""

    def __init__(self, scorer: Scorer, threshold: float) -> None:
        self._scorer = scorer
        self._threshold = threshold
        self._pending = b""
        self._cooldown = 0

    def feed(self, pcm: bytes) -> float | None:
        """PCM 을 이어 넣는다. 이번에 깨어났으면 그 점수, 아니면 None."""
        data = self._pending + pcm
        usable = len(data) - len(data) % FRAME_BYTES
        self._pending = data[usable:]
        woke: float | None = None
        for start in range(0, usable, FRAME_BYTES):
            # 무시하는 동안에도 점수는 매긴다. 모델이 앞 프레임을 이어 보는 내부 버퍼를 갖고 있다
            score = self._scorer(data[start : start + FRAME_BYTES])
            if self._cooldown > 0:
                self._cooldown -= 1
            elif score >= self._threshold:
                woke = score
                self._cooldown = REFRACTORY_FRAMES
        return woke


def missing_wake_files(model_dir: str) -> list[str]:
    root = Path(model_dir).expanduser()
    return [name for name in WAKE_MODEL_FILES if not (root / name).is_file()]


def openwakeword_scorer(model_dir: str) -> Scorer:
    """openWakeWord 모델 하나를 띄운다. 모델이 앞 프레임을 기억하므로 연결마다 따로 만든다.

    설치: uv sync --extra wake
    """
    try:
        import numpy as np
        from openwakeword.model import Model
    except ImportError as exc:
        raise ImportError("openwakeword 가 설치되지 않았습니다. `uv sync --extra wake` 로 설치하세요.") from exc
    missing = missing_wake_files(model_dir)
    if missing:
        raise FileNotFoundError(f"웨이크워드 모델 파일이 없습니다: {', '.join(missing)} ({model_dir})")
    root = Path(model_dir).expanduser()
    model = Model(
        wakeword_models=[str(root / WAKE_MODEL)],
        inference_framework="onnx",
        melspec_model_path=str(root / MELSPEC_MODEL),
        embedding_model_path=str(root / EMBEDDING_MODEL),
    )
    key = Path(WAKE_MODEL).stem

    def score(frame: bytes) -> float:
        return float(model.predict(np.frombuffer(frame, dtype=np.int16))[key])

    return score
