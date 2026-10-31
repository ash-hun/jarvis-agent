"""voice: 가짜 supertonic 모듈로 SupertonicTTSProvider 의 WAV 합성과 미설치 오류를 검증한다."""

import io
import sys
import wave
import pytest
from typing import Any
from types import ModuleType

from jarvis.voice.providers.supertonic import SupertonicTTSProvider

np = pytest.importorskip("numpy")


class _FakeTTS:
    """supertonic 1.3 의 TTS 모양. synthesize 는 ((1, N) 파형, 길이)를 돌려준다."""

    sample_rate = 16000
    instances: list["_FakeTTS"] = []

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls: list[tuple[str, str, str]] = []
        self.instances.append(self)

    def get_voice_style(self, voice_name: str) -> str:
        return f"style:{voice_name}"

    def synthesize(self, text: str, voice_style: str, lang: str | None = None) -> tuple[Any, Any]:
        self.calls.append((text, voice_style, str(lang)))
        return np.array([[0.0, 0.5, -2.0]], dtype=np.float32), np.array([0.1])


def _install_fake(monkeypatch: pytest.MonkeyPatch, sample_rate: int) -> None:
    module = ModuleType("supertonic")
    module.TTS = _FakeTTS  # type: ignore[attr-defined]  # 가짜 모듈에 속성을 붙인다
    monkeypatch.setitem(sys.modules, "supertonic", module)
    monkeypatch.setattr(_FakeTTS, "instances", [])
    monkeypatch.setattr(_FakeTTS, "sample_rate", sample_rate)


def _read_wav(data: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.readframes(wf.getnframes())


@pytest.mark.parametrize("sample_rate", [16000, 22050])
async def test_synthesize_returns_mono_16bit_wav_at_model_rate(monkeypatch: pytest.MonkeyPatch, sample_rate) -> None:
    _install_fake(monkeypatch, sample_rate)

    wav = await SupertonicTTSProvider().synthesize("안녕", lang="en")

    channels, width, rate, frames = _read_wav(wav)
    assert (channels, width, rate) == (1, 2, sample_rate)
    # 범위를 넘는 -2.0 은 -1.0 으로 잘린다
    assert list(np.frombuffer(frames, dtype=np.int16)) == [0, 16383, -32767]
    [tts] = _FakeTTS.instances
    assert tts.calls == [("안녕", "style:F1", "en")]
    assert tts.model_name == "supertonic-3"


def test_init_missing_package_raises_import_error_with_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "supertonic", None)

    with pytest.raises(ImportError, match="supertonic"):
        SupertonicTTSProvider()
