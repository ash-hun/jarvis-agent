"""PiperTTSProvider 와 영어 라우팅: 가짜 piper 모듈로 WAV 합성, 모델 누락, 언어별 프로바이더 선택을 검증한다."""

import io
import sys
import wave
import pytest
from pathlib import Path
from types import ModuleType

from jarvis.voice.protocol import STTProvider, TTSProvider
from jarvis.voice.providers.piper import PiperTTSProvider
from jarvis.voice.service import VoiceService, is_english
from jarvis.config import VoiceConfig


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


class _Recorder(TTSProvider):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        self.calls.append((text, lang))
        return self.name.encode()


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


def test_missing_model_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _install_fake(monkeypatch)
    with pytest.raises(FileNotFoundError, match="Piper 음성 모델"):
        PiperTTSProvider(str(tmp_path / "none.onnx"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Good evening, sir. All systems are online.", True),
        ("안녕하세요, 오늘 일정 알려드릴게요.", False),
        ("오늘 PR 두 개 머지했어요.", False),
        ("12:30", False),
        ("こんにちは", False),
    ],
)
def test_is_english(text: str, expected: bool) -> None:
    assert is_english(text) is expected


async def test_english_text_goes_to_english_tts() -> None:
    default, english = _Recorder("default"), _Recorder("english")
    service = VoiceService(STTProvider(), default, english_tts=english)

    assert await service.synthesize("Shall I render the suit, sir?", "ko") == b"english"
    assert await service.synthesize("수트를 렌더링할까요?", "ko") == b"default"
    assert english.calls == [("Shall I render the suit, sir?", "en")]
    assert default.calls == [("수트를 렌더링할까요?", "ko")]


async def test_without_english_tts_everything_goes_to_default() -> None:
    default = _Recorder("default")
    service = VoiceService(STTProvider(), default)

    assert await service.synthesize("Hello there.") == b"default"


def test_english_tts_options_only_for_piper() -> None:
    assert VoiceConfig(english_tts_provider="piper", piper_model="/m.onnx").english_tts_options() == {
        "model_path": "/m.onnx",
        "noise_scale": 0.4,
    }
    assert VoiceConfig().english_tts_options() == {}
