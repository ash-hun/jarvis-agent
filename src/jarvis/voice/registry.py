"""[voice] 이름으로 STT/TTS 프로바이더를 지연 임포트해 만드는 레지스트리를 제공한다."""

from __future__ import annotations

from collections.abc import Callable

from jarvis.voice.protocol import STTProvider, TTSProvider

# ── STT 레지스트리 ─────────────────────────────────────────────────────────────
# 키: provider 이름(소문자), 값: 팩토리. 팩토리는 지연 임포트로 선택적 deps 를 보호한다
_STT_REGISTRY: dict[str, Callable[..., STTProvider]] = {}
_TTS_REGISTRY: dict[str, Callable[..., TTSProvider]] = {}


def _lazy_stt(module: str, cls: str) -> Callable[..., STTProvider]:
    def factory(**kwargs: object) -> STTProvider:
        import importlib
        provider: STTProvider = getattr(importlib.import_module(module), cls)(**kwargs)
        return provider
    return factory


def _lazy_tts(module: str, cls: str) -> Callable[..., TTSProvider]:
    def factory(**kwargs: object) -> TTSProvider:
        import importlib
        provider: TTSProvider = getattr(importlib.import_module(module), cls)(**kwargs)
        return provider
    return factory


# 기본 제공 STT 프로바이더 등록
_STT_REGISTRY["browser"] = _lazy_stt("jarvis.voice.providers.browser", "BrowserSTTProvider")
_STT_REGISTRY["whisper"] = _lazy_stt("jarvis.voice.providers.whisper", "WhisperSTTProvider")

# 기본 제공 TTS 프로바이더 등록
_TTS_REGISTRY["browser"] = _lazy_tts("jarvis.voice.providers.browser", "BrowserTTSProvider")
_TTS_REGISTRY["supertonic"] = _lazy_tts("jarvis.voice.providers.supertonic", "SupertonicTTSProvider")


def register_stt(name: str, factory: Callable[..., STTProvider]) -> None:
    """외부 STT 프로바이더를 레지스트리에 등록."""
    _STT_REGISTRY[name.lower()] = factory


def register_tts(name: str, factory: Callable[..., TTSProvider]) -> None:
    """외부 TTS 프로바이더를 레지스트리에 등록."""
    _TTS_REGISTRY[name.lower()] = factory


def make_stt(provider_name: str, **kwargs: object) -> STTProvider:
    """STT 프로바이더 팩토리.

    provider_name:
        "browser"  : Web Speech API 위임 (서버 처리 없음, 기본값)
        "whisper"  : faster-whisper 로컬 STT (pip install faster-whisper)
    """
    name = provider_name.lower()
    factory = _STT_REGISTRY.get(name)
    if factory is None:
        available = ", ".join(sorted(_STT_REGISTRY))
        raise ValueError(f"알 수 없는 STT 프로바이더: {provider_name!r}. 사용 가능: {available}")
    return factory(**kwargs)


def make_tts(provider_name: str, **kwargs: object) -> TTSProvider:
    """TTS 프로바이더 팩토리.

    provider_name:
        "browser"     : Web Speech API 위임 (서버 처리 없음, 기본값)
        "supertonic"  : Supertonic-3 ONNX TTS (pip install supertonic)
    """
    name = provider_name.lower()
    factory = _TTS_REGISTRY.get(name)
    if factory is None:
        available = ", ".join(sorted(_TTS_REGISTRY))
        raise ValueError(f"알 수 없는 TTS 프로바이더: {provider_name!r}. 사용 가능: {available}")
    return factory(**kwargs)
