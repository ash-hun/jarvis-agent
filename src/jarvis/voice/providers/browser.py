from __future__ import annotations


class BrowserSTTProvider:
    """STT를 브라우저의 Web Speech API에 위임한다. 서버 측 처리 없음."""

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        raise NotImplementedError(
            "BrowserSTTProvider: transcription happens client-side via Web Speech API"
        )


class BrowserTTSProvider:
    """TTS를 브라우저의 Web Speech API에 위임한다.

    synthesize()가 빈 bytes를 반환하면 클라이언트가 browser TTS fallback을 실행한다.
    """

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        return b""
