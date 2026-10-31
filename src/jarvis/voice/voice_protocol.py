"""[voice] STT/TTS 프로바이더가 상속하는 기본 클래스를 정의하고, 기본 동작은 브라우저 위임이다."""

from dataclasses import dataclass
from collections.abc import AsyncIterator

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_LANG = "ko"


@dataclass(frozen=True)
class Transcript:
    """전사 글과 확신도. 확신도를 모르는 프로바이더는 확실한 쪽 값(0.0, 0.0)을 둔다."""

    text: str
    # 말소리가 없을 확률(구간 중 최댓값)
    no_speech_prob: float = 0.0
    # 토큰 평균 로그 확률(구간 평균). 0 에 가까울수록 확실하다
    avg_logprob: float = 0.0


class STTProvider:
    """Speech-to-Text 기본 클래스. 기본 동작은 브라우저 Web Speech API 위임(서버 전사 없음)이다."""

    async def transcribe_scored(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        """확신도를 함께 준다. 확신도를 모르는 프로바이더는 글만 채운다."""
        return Transcript(await self.transcribe(audio_bytes, sample_rate))

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
        """PCM/WAV 오디오 바이트를 텍스트로 변환한다."""
        # 전사는 클라이언트의 Web Speech API에서 수행되므로 서버는 호출되지 않는다.
        # 방어적으로 호출되더라도 빈 문자열을 돌려 메인 흐름을 막지 않는다
        # (TTSProvider.synthesize()가 빈 bytes를 돌리는 것과 동일한 규약).
        return ""


class TTSProvider:
    """Text-to-Speech 기본 클래스. 기본 동작은 브라우저 Web Speech API 위임이다."""

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        """텍스트를 WAV 오디오 바이트로 합성한다. browser TTS 위임 시 빈 bytes 반환."""
        # 빈 bytes 를 받으면 클라이언트가 browser TTS fallback 을 실행한다
        return b""

    async def synthesize_stream(self, text: str, lang: str = DEFAULT_LANG) -> AsyncIterator[bytes]:
        """나오는 대로 WAV 조각을 낸다. 조각으로 못 내는 프로바이더는 한 번에 합성한 한 조각이다. 비면 내지 않는다."""
        audio = await self.synthesize(text, lang)
        if audio:
            yield audio
