"""WhisperSTTProvider: 가짜 faster_whisper 모듈로 전사 결합과 미설치 오류를 검증한다(실제 모델 없음)."""

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from jarvis.voice.providers.whisper import WhisperSTTProvider


class _FakeModel:
    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        self.init = (model_size, device, compute_type)
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, language: str) -> tuple[list[Any], None]:
        self.calls.append({"audio": audio.read(), "language": language})
        return [SimpleNamespace(text=" 안녕"), SimpleNamespace(text="하세요 ")], None


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("faster_whisper")
    module.WhisperModel = _FakeModel  # type: ignore[attr-defined]  # 가짜 모듈에 속성을 붙인다
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


async def test_transcribe_joins_and_strips_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)
    provider = WhisperSTTProvider(model_size="tiny")
    assert await provider.transcribe(b"pcm") == "안녕하세요"
    model: _FakeModel = provider._model
    assert model.init == ("tiny", "cpu", "int8")
    assert model.calls == [{"audio": b"pcm", "language": "ko"}]


def test_missing_package_raises_import_error_with_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(ImportError, match="faster-whisper"):
        WhisperSTTProvider()
