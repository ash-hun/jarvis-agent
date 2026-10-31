"""[voice] faster-whisper 로 서버에서 음성을 전사하는 로컬 STT 프로바이더."""

import io
import asyncio
from functools import partial

from jarvis.voice.voice_protocol import DEFAULT_SAMPLE_RATE, STTProvider, Transcript


class WhisperSTTProvider(STTProvider):
    """faster-whisper 기반 로컬 STT 프로바이더.

    설치: pip install faster-whisper
    모델 크기: tiny / base / small / medium / large-v3
    """

    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]  # 스텁 없는 선택 의존성
        except ImportError as exc:
            raise ImportError(
                "faster-whisper가 설치되지 않았습니다. `pip install faster-whisper` 로 설치하세요."
            ) from exc
        self._model = WhisperModel(model_size, device=device, compute_type="int8")

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
        return (await self.transcribe_scored(audio_bytes, sample_rate)).text

    async def transcribe_scored(self, audio_bytes: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Transcript:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._transcribe_sync, audio_bytes))

    def _transcribe_sync(self, audio_bytes: bytes) -> Transcript:
        segments, _ = self._model.transcribe(io.BytesIO(audio_bytes), language="ko")
        segs = list(segments)
        text = "".join(seg.text for seg in segs).strip()
        if not segs:
            return Transcript(text)
        return Transcript(
            text,
            no_speech_prob=max(float(getattr(s, "no_speech_prob", 0.0)) for s in segs),
            avg_logprob=sum(float(getattr(s, "avg_logprob", 0.0)) for s in segs) / len(segs),
        )
