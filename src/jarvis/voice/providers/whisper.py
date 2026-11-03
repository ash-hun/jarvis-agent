"""[voice] faster-whisper 로 서버에서 음성을 전사하는 로컬 STT 프로바이더."""

import io
import asyncio
from typing import Any
from functools import partial

from jarvis.voice.voice_protocol import DEFAULT_SAMPLE_RATE, STTProvider, Transcript

# 사용자는 한국어로 말하고 JARVIS 는 영어로 말을 건다. 감지가 둘 밖으로 가면 둘 중 확률이 높은 쪽으로 다시 받아 적는다
LANGUAGES = ("ko", "en")
# 이름을 비슷한 소리의 낱말(Travis, J-B-E-S)로 적지 않게 표기를 알려 준다
HOTWORDS = "Jarvis"


def pick_language(detected: str, probs: list[tuple[str, float]] | None) -> str | None:
    """감지한 언어가 LANGUAGES 안이면 None(그대로 쓴다). 밖이면 LANGUAGES 중 확률이 가장 높은 언어."""
    if detected in LANGUAGES:
        return None
    scores = dict(probs or [])
    return max(LANGUAGES, key=lambda lang: scores.get(lang, 0.0))


class WhisperSTTProvider(STTProvider):
    """faster-whisper 기반 로컬 STT 프로바이더.

    설치: pip install faster-whisper
    모델 크기: tiny / base / small / medium / large-v3
    """

    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        try:
            from faster_whisper import WhisperModel
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
        # 언어 감지는 transcribe 호출 때 끝나고, segments 는 꺼낼 때 해독한다. 다시 부르면 감지 비용만 한 번 더 든다
        segments, info = self._run(audio_bytes, None)
        retry = pick_language(info.language, info.all_language_probs)
        if retry:
            segments, _ = self._run(audio_bytes, retry)
        segs = list(segments)
        text = "".join(seg.text for seg in segs).strip()
        if not segs:
            return Transcript(text)
        return Transcript(
            text,
            no_speech_prob=max(float(getattr(s, "no_speech_prob", 0.0)) for s in segs),
            avg_logprob=sum(float(getattr(s, "avg_logprob", 0.0)) for s in segs) / len(segs),
        )

    def _run(self, audio_bytes: bytes, language: str | None) -> tuple[Any, Any]:
        # vad_filter: 말 끝 무음을 잘라 낸다. 무음을 해독하면 "다음 영상에서 만나요" 같은 환청이 붙는다
        return self._model.transcribe(  # type: ignore[no-any-return]
            io.BytesIO(audio_bytes), language=language, vad_filter=True, hotwords=HOTWORDS
        )
