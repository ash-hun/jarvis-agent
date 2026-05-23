from __future__ import annotations

import asyncio
import io
from functools import partial


class WhisperSTTProvider:
    """faster-whisper 기반 로컬 STT 프로바이더.

    설치: pip install faster-whisper
    모델 크기: tiny / base / small / medium / large-v3
    """

    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "faster-whisper가 설치되지 않았습니다. `pip install faster-whisper` 로 설치하세요."
            ) from exc
        self._model = WhisperModel(model_size, device=device, compute_type="int8")

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._transcribe_sync, audio_bytes))

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        segments, _ = self._model.transcribe(io.BytesIO(audio_bytes), language="ko")
        return "".join(seg.text for seg in segments).strip()
