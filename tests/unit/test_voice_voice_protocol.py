"""voice: STT/TTS 기본 클래스의 기본 동작(브라우저 위임)과 구현체의 상속 관계."""

import pytest

from jarvis.voice.providers.browser import BrowserSTTProvider, BrowserTTSProvider
from jarvis.voice.providers.supertonic import SupertonicTTSProvider
from jarvis.voice.voice_protocol import STTProvider, TTSProvider
from jarvis.voice.providers.whisper import WhisperSTTProvider


@pytest.mark.parametrize("stt", [STTProvider, BrowserSTTProvider])
async def test_default_transcribe_returns_empty_so_the_browser_transcribes(stt):
    assert await stt().transcribe(b"audio") == ""


@pytest.mark.parametrize("tts", [TTSProvider, BrowserTTSProvider])
async def test_default_synthesize_returns_empty_so_the_browser_speaks(tts):
    assert await tts().synthesize("안녕") == b""


def test_implementations_inherit_base() -> None:
    assert issubclass(BrowserSTTProvider, STTProvider) and issubclass(WhisperSTTProvider, STTProvider)
    assert issubclass(BrowserTTSProvider, TTSProvider) and issubclass(SupertonicTTSProvider, TTSProvider)
