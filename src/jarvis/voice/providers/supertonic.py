from __future__ import annotations

import asyncio
import io
import wave
from functools import partial


class SupertonicTTSProvider:
    """Supertonic-3 ONNX 기반 로컬 TTS 프로바이더.

    설치: pip install supertonic
    모델: Supertone/supertonic-3 (HuggingFace)
    지원 언어: 31개 언어 (한국어 포함)

    API 참고:
        https://huggingface.co/Supertone/supertonic-3
    """

    def __init__(self, model_name: str = "Supertone/supertonic-3") -> None:
        try:
            import supertonic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "supertonic이 설치되지 않았습니다. `pip install supertonic` 으로 설치하세요."
            ) from exc
        self._tts = supertonic.TTS(model_name)

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._synthesize_sync, text, lang))

    def _synthesize_sync(self, text: str, lang: str) -> bytes:
        import numpy as np  # type: ignore[import]

        audio: np.ndarray = self._tts.tts(text, language=lang)
        sample_rate: int = getattr(self._tts, "sample_rate", 22050)
        return _array_to_wav(audio, sample_rate)


def _array_to_wav(audio: "np.ndarray", sample_rate: int) -> bytes:  # type: ignore[name-defined]
    import numpy as np

    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()
