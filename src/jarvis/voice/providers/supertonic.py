"""[voice] Supertonic-3 ONNX 로 서버에서 음성을 합성하는 로컬 TTS 프로바이더."""

import io
import wave
import asyncio
from typing import Any
from functools import partial

from jarvis.voice.voice_protocol import DEFAULT_LANG, TTSProvider

DEFAULT_MODEL = "supertonic-3"
# supertonic-3 기본 음성 10개(M1~M5, F1~F5) 중 하나
DEFAULT_VOICE = "F1"


class SupertonicTTSProvider(TTSProvider):
    """Supertonic-3 ONNX 기반 로컬 TTS 프로바이더.

    설치: uv sync --extra voice (또는 discord). 모델은 처음 쓸 때 HuggingFace 에서 받는다. 한국어 포함 31개 언어.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE) -> None:
        try:
            import supertonic
        except ImportError as exc:
            raise ImportError(
                "supertonic이 설치되지 않았습니다. `pip install supertonic` 으로 설치하세요."
            ) from exc
        self._tts = supertonic.TTS(model_name)
        self._style = self._tts.get_voice_style(voice)

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._synthesize_sync, text, lang))

    def _synthesize_sync(self, text: str, lang: str) -> bytes:
        # supertonic 1.3 API: synthesize(text, voice_style, lang=) → (파형, 길이). 파형은 (1, N) 모양이다
        audio, _duration = self._tts.synthesize(text, voice_style=self._style, lang=lang)
        return _array_to_wav(audio.reshape(-1), int(self._tts.sample_rate))


def _array_to_wav(audio: Any, sample_rate: int) -> bytes:  # audio: supertonic 이 돌려주는 float 배열(스텁 없음)
    import numpy as np

    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()
