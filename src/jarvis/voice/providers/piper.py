"""[voice] Piper ONNX 음성 모델 하나로 서버에서 음성을 합성하는 로컬 TTS 프로바이더."""

import asyncio
import io
import wave
from functools import partial
from pathlib import Path

from jarvis.voice.protocol import DEFAULT_LANG, TTSProvider


class PiperTTSProvider(TTSProvider):
    """Piper 음성 모델(.onnx 와 같은 자리의 .onnx.json)로 합성한다. 모델이 한 언어라 lang 은 보지 않는다.

    설치: uv sync --extra piper
    """

    def __init__(self, model_path: str) -> None:
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise ImportError("piper-tts 가 설치되지 않았습니다. `uv sync --extra piper` 로 설치하세요.") from exc
        path = Path(model_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Piper 음성 모델이 없습니다: {path}")
        self._voice = PiperVoice.load(path)

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._synthesize_sync, text))

    def _synthesize_sync(self, text: str) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._voice.synthesize_wav(text, wf)
        return buf.getvalue()
