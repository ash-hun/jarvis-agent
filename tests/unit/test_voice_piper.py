"""voice: 가짜 piper 모듈로 PiperTTSProvider 의 WAV 합성과 모델 누락 오류를 검증한다."""

import io
import sys
import wave
import pytest
from pathlib import Path
from types import ModuleType

from jarvis.voice.providers.piper import PiperTTSProvider


class _FakeConfig:
    def __init__(self, noise_scale: float | None = None) -> None:
        self.noise_scale = noise_scale


class _FakeVoice:
    loaded: list[Path] = []
    configs: list[_FakeConfig] = []

    @classmethod
    def load(cls, path: Path) -> "_FakeVoice":
        cls.loaded.append(path)
        return cls()

    def synthesize_wav(self, text: str, wav_file: wave.Wave_write, syn_config: _FakeConfig) -> None:
        self.configs.append(syn_config)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x01" * len(text))


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("piper")
    module.PiperVoice = _FakeVoice  # type: ignore[attr-defined]  # 가짜 모듈에 속성을 붙인다
    module.SynthesisConfig = _FakeConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", module)


async def test_synthesize_returns_wav_from_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake(monkeypatch)
    model = tmp_path / "en-voice.onnx"
    model.write_bytes(b"")

    audio = await PiperTTSProvider(str(model), noise_scale=0.4).synthesize("Good evening, sir.")

    with wave.open(io.BytesIO(audio), "rb") as wf:
        assert (wf.getnchannels(), wf.getframerate(), wf.getnframes()) == (1, 22050, len("Good evening, sir."))
    assert _FakeVoice.loaded[-1] == model
    assert _FakeVoice.configs[-1].noise_scale == 0.4


def test_init_missing_model_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake(monkeypatch)

    with pytest.raises(FileNotFoundError, match="Piper 음성 모델"):
        PiperTTSProvider(str(tmp_path / "none.onnx"))
