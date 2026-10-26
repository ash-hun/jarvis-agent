"""[voice] STT 와 TTS 프로바이더를 묶어 하나의 음성 파이프라인으로 제공한다."""

import re

from jarvis.voice.protocol import DEFAULT_LANG, DEFAULT_SAMPLE_RATE, STTProvider, Transcript, TTSProvider

ENGLISH_LANG = "en"
# faster-whisper 가 구간을 버리는 기본 기준과 같다. 실제 기록(로그의 [Voice] stt 줄)을 보며 맞춘다
NO_SPEECH_MAX = 0.6
AVG_LOGPROB_MIN = -1.0
# 한글, 가나, 한자가 한 글자라도 있으면 영어 음성 모델이 읽지 못한다
_NON_LATIN_SCRIPT = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u4e00-\u9fff\uac00-\ud7a3]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def is_english(text: str) -> bool:
    """라틴 문자만으로 된 문장이면 True. 한국어 문장 속 영어 단어는 한국어로 본다."""
    return bool(_LATIN_LETTER.search(text)) and not _NON_LATIN_SCRIPT.search(text)


def is_unclear(t: Transcript) -> bool:
    """글이 비었거나, 말소리가 없었을 것 같거나, 받아 적은 글을 모델이 확신하지 못하면 True."""
    return not t.text.strip() or t.no_speech_prob > NO_SPEECH_MAX or t.avg_logprob < AVG_LOGPROB_MIN


class VoiceService:
    """STT + TTS 프로바이더를 통합해 음성 파이프라인을 제공한다. english_tts 가 있으면 영어 문장은 그쪽이 읽는다."""

    def __init__(self, stt: STTProvider, tts: TTSProvider, english_tts: TTSProvider | None = None) -> None:
        self._stt = stt
        self._tts = tts
        self._english_tts = english_tts

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
        return await self._stt.transcribe(audio_bytes, sample_rate)

    async def transcribe_scored(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        scored = getattr(self._stt, "transcribe_scored", None)
        if scored is None:
            return Transcript(await self._stt.transcribe(audio_bytes, sample_rate))
        result: Transcript = await scored(audio_bytes, sample_rate)
        return result

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        """텍스트 → WAV bytes. 빈 bytes이면 클라이언트가 browser TTS를 사용해야 함."""
        if self._english_tts is not None and is_english(text):
            return await self._english_tts.synthesize(text, ENGLISH_LANG)
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
    def from_config(
        cls,
        stt_provider: str,
        tts_provider: str,
        stt_options: dict[str, object] | None = None,
        tts_options: dict[str, object] | None = None,
        english_tts_provider: str = "",
        english_tts_options: dict[str, object] | None = None,
    ) -> "VoiceService":
        """프로바이더 이름과 각자의 생성 옵션으로 만든다. 옵션은 그 프로바이더 팩토리에만 넘긴다."""
        from jarvis.voice.registry import make_stt, make_tts

        english_tts = make_tts(english_tts_provider, **(english_tts_options or {})) if english_tts_provider else None
        return cls(
            stt=make_stt(stt_provider, **(stt_options or {})),
            tts=make_tts(tts_provider, **(tts_options or {})),
            english_tts=english_tts,
        )
