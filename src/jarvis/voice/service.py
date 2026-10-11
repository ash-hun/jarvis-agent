"""[voice] STT 와 TTS 프로바이더를 묶어 하나의 음성 파이프라인으로 제공한다."""

from __future__ import annotations

from jarvis.voice.protocol import DEFAULT_LANG, DEFAULT_SAMPLE_RATE, STTProvider, TTSProvider


class VoiceService:
    """STT + TTS 프로바이더를 통합해 음성 파이프라인을 제공한다."""

    def __init__(self, stt: STTProvider, tts: TTSProvider) -> None:
        self._stt = stt
        self._tts = tts

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
        return await self._stt.transcribe(audio_bytes, sample_rate)

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        """텍스트 → WAV bytes. 빈 bytes이면 클라이언트가 browser TTS를 사용해야 함."""
        return await self._tts.synthesize(text, lang)

    @property
    def tts_is_browser(self) -> bool:
        from jarvis.voice.providers.browser import BrowserTTSProvider
        return isinstance(self._tts, BrowserTTSProvider)

    @property
    def stt_is_browser(self) -> bool:
        from jarvis.voice.providers.browser import BrowserSTTProvider
        return isinstance(self._stt, BrowserSTTProvider)

    @classmethod
    def from_config(cls, stt_provider: str, tts_provider: str, **kwargs: object) -> VoiceService:
        from jarvis.voice.registry import make_stt, make_tts
        return cls(stt=make_stt(stt_provider), tts=make_tts(tts_provider))
