from __future__ import annotations

from jarvis.voice.protocol import STTProvider, TTSProvider


def make_stt(provider_name: str, **kwargs: object) -> STTProvider:
    """STT 프로바이더 팩토리.

    provider_name:
        "browser"  — Web Speech API 위임 (서버 처리 없음, 기본값)
        "whisper"  — faster-whisper 로컬 STT (pip install faster-whisper)
    """
    name = provider_name.lower()
    if name == "browser":
        from jarvis.voice.providers.browser import BrowserSTTProvider
        return BrowserSTTProvider()
    if name == "whisper":
        from jarvis.voice.providers.whisper import WhisperSTTProvider
        return WhisperSTTProvider(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"알 수 없는 STT 프로바이더: {provider_name!r}")


def make_tts(provider_name: str, **kwargs: object) -> TTSProvider:
    """TTS 프로바이더 팩토리.

    provider_name:
        "browser"     — Web Speech API 위임 (서버 처리 없음, 기본값)
        "supertonic"  — Supertonic-3 ONNX TTS (pip install supertonic)
    """
    name = provider_name.lower()
    if name == "browser":
        from jarvis.voice.providers.browser import BrowserTTSProvider
        return BrowserTTSProvider()
    if name == "supertonic":
        from jarvis.voice.providers.supertonic import SupertonicTTSProvider
        return SupertonicTTSProvider(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"알 수 없는 TTS 프로바이더: {provider_name!r}")
