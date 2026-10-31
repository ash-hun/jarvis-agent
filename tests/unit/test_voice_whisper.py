"""voice: 가짜 faster_whisper 모듈로 WhisperSTTProvider 의 전사 결합, 확신도, 미설치 오류를 검증한다."""

import sys
import pytest
from typing import Any
from types import ModuleType, SimpleNamespace

from jarvis.voice.providers.whisper import WhisperSTTProvider


class _FakeModel:
    instances: list["_FakeModel"] = []
    segments: list[Any] = []

    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self.init = (model_size, device, compute_type)
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    def transcribe(self, audio: Any, language: str) -> tuple[list[Any], None]:
        self.calls.append({"audio": audio.read(), "language": language})
        return self.segments, None


def _install_fake(monkeypatch: pytest.MonkeyPatch, segments: list[Any]) -> None:
    module = ModuleType("faster_whisper")
    module.WhisperModel = _FakeModel  # type: ignore[attr-defined]  # 가짜 모듈에 속성을 붙인다
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(_FakeModel, "instances", [])
    monkeypatch.setattr(_FakeModel, "segments", segments)


async def test_transcribe_joins_and_strips_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch, [SimpleNamespace(text=" 안녕"), SimpleNamespace(text="하세요 ")])

    text = await WhisperSTTProvider(model_size="tiny").transcribe(b"pcm")

    assert text == "안녕하세요"
    [model] = _FakeModel.instances
    assert model.init == ("tiny", "cpu", "int8")
    assert model.calls == [{"audio": b"pcm", "language": "ko"}]


async def test_transcribe_scored_takes_worst_no_speech_and_mean_logprob(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(
        monkeypatch,
        [
            SimpleNamespace(text=" 지금", no_speech_prob=0.1, avg_logprob=-0.2),
            SimpleNamespace(text=" 몇 시야", no_speech_prob=0.7, avg_logprob=-0.6),
        ],
    )

    heard = await WhisperSTTProvider(model_size="tiny").transcribe_scored(b"pcm")

    assert heard.text == "지금 몇 시야"
    assert heard.no_speech_prob == 0.7 and abs(heard.avg_logprob - (-0.4)) < 1e-9


def test_init_missing_package_raises_import_error_with_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    with pytest.raises(ImportError, match="faster-whisper"):
        WhisperSTTProvider()
