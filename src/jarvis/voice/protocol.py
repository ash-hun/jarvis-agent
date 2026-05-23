from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class STTProvider(Protocol):
    """Speech-to-Text 추상 인터페이스."""

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """PCM/WAV 오디오 바이트를 텍스트로 변환한다."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    """Text-to-Speech 추상 인터페이스."""

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        """텍스트를 WAV 오디오 바이트로 합성한다. browser TTS 위임 시 빈 bytes 반환."""
        ...
