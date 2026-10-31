"""voice: 이름으로 STT/TTS 프로바이더를 만들고, 모르는 이름은 거절하고, 외부 프로바이더를 등록한다."""

import pytest

from jarvis.voice.providers.browser import BrowserSTTProvider, BrowserTTSProvider
from jarvis.voice.voice_registry import make_stt, make_tts, register_stt


@pytest.mark.parametrize(("make", "expected"), [(make_stt, BrowserSTTProvider), (make_tts, BrowserTTSProvider)])
def test_make_browser_returns_browser_provider(make, expected):
    assert isinstance(make("browser"), expected)


@pytest.mark.parametrize(("make", "message"), [(make_stt, "알 수 없는 STT"), (make_tts, "알 수 없는 TTS")])
def test_make_unknown_name_raises(make, message):
    with pytest.raises(ValueError, match=message):
        make("nonexistent")


def test_register_stt_makes_the_custom_provider_by_name():
    class FakeSTT:
        async def transcribe(self, audio_bytes, sample_rate=16000):
            return "fake"

    register_stt("fake-stt", lambda **kw: FakeSTT())

    assert isinstance(make_stt("fake-stt"), FakeSTT)
