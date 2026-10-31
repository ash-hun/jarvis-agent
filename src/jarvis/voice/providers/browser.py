"""[voice] STT/TTS 를 브라우저 Web Speech API 에 맡기는 프로바이더(서버 측 처리 없음)."""

from jarvis.voice.voice_protocol import STTProvider, TTSProvider


class BrowserSTTProvider(STTProvider):
    """STT를 브라우저의 Web Speech API에 위임한다. 서버 측 처리 없음(기본 클래스 동작 그대로)."""


class BrowserTTSProvider(TTSProvider):
    """TTS를 브라우저의 Web Speech API에 위임한다.

    synthesize()가 빈 bytes를 반환하면 클라이언트가 browser TTS fallback을 실행한다.
    """
