from __future__ import annotations


class BrowserSTTProvider:
    """STT를 브라우저의 Web Speech API에 위임한다. 서버 측 처리 없음."""

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        # 전사는 클라이언트의 Web Speech API에서 수행되므로 서버는 호출되지 않는다.
        # 방어적으로 호출되더라도 빈 문자열을 돌려 메인 흐름을 막지 않는다
        # (BrowserTTSProvider.synthesize()가 빈 bytes를 돌리는 것과 동일한 규약).
        return ""


class BrowserTTSProvider:
    """TTS를 브라우저의 Web Speech API에 위임한다.

    synthesize()가 빈 bytes를 반환하면 클라이언트가 browser TTS fallback을 실행한다.
    """

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        return b""
