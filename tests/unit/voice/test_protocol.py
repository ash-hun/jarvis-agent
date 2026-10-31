"""STT/TTS 기본 클래스: 기본 동작(브라우저 위임)과 구현체의 상속 관계를 확인한다."""

from jarvis.voice.providers.browser import BrowserSTTProvider, BrowserTTSProvider
from jarvis.voice.providers.supertonic import SupertonicTTSProvider
from jarvis.voice.voice_protocol import STTProvider, TTSProvider
from jarvis.voice.providers.whisper import WhisperSTTProvider
from jarvis.voice.voice_service import VoiceService


async def test_base_defaults_delegate_to_browser() -> None:
    assert await STTProvider().transcribe(b"audio") == ""
    assert await TTSProvider().synthesize("안녕") == b""


def test_implementations_inherit_base() -> None:
    assert issubclass(BrowserSTTProvider, STTProvider) and issubclass(WhisperSTTProvider, STTProvider)
    assert issubclass(BrowserTTSProvider, TTSProvider) and issubclass(SupertonicTTSProvider, TTSProvider)


def test_bare_base_is_not_reported_as_browser() -> None:
    """tts_is_browser/stt_is_browser 는 Browser 구현체만 브라우저로 본다."""
    service = VoiceService(stt=STTProvider(), tts=TTSProvider())
    assert service.stt_is_browser is False and service.tts_is_browser is False
