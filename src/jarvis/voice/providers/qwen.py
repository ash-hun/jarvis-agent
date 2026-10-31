"""[voice] Mac 호스트의 Qwen3-TTS 합성 서버(services/qwen_tts)를 부르고, 닿지 않으면 Piper 로 읽는 영어 TTS."""

import io
import wave
import httpx
import struct
from collections.abc import AsyncIterator

from jarvis.voice.voice_protocol import DEFAULT_LANG, TTSProvider
from jarvis.common.logger import get_logger

# 서버가 꺼져 있으면 바로 Piper 로 넘어가도록 연결은 짧게, 합성(긴 문장 3초쯤)은 넉넉히 기다린다
CONNECT_TIMEOUT_SEC = 1.0
SYNTH_TIMEOUT_SEC = 20.0
# 합성 서버의 조각: 4바이트 길이(LE) + PCM s16le 모노. 길이 0 이 끝이다
FRAME_HEADER = struct.Struct("<I")
DEFAULT_SAMPLE_RATE = 24000

logger = get_logger(__name__)


class QwenTTSProvider(TTSProvider):
    """합성은 Mac GPU 가 하는 서버에 맡긴다. Docker 안에서는 GPU 를 못 써 같은 모델이 수백 배 느렸다(2026-10-27 측정).

    piper_model 을 주면 서버에 닿지 않거나 실패할 때 그 Piper 음성으로 읽는다. 없으면 오류를 그대로 낸다.
    """

    def __init__(
        self,
        url: str,
        piper_model: str = "",
        noise_scale: float | None = None,
        fallback: TTSProvider | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url.rstrip("/") + "/tts"
        self._stream_url = self._url + "/stream"
        timeout = httpx.Timeout(SYNTH_TIMEOUT_SEC, connect=CONNECT_TIMEOUT_SEC)
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._fallback = fallback if fallback is not None else _piper(piper_model, noise_scale)

    async def synthesize(self, text: str, lang: str = DEFAULT_LANG) -> bytes:
        try:
            response = await self._client.post(self._url, json={"text": text})
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            if self._fallback is None:
                raise
            logger.info(f"[Voice] qwen 합성 서버에 닿지 않아 Piper 로 읽는다: {exc!r}")
            return await self._fallback.synthesize(text, lang)

    async def synthesize_stream(self, text: str, lang: str = DEFAULT_LANG) -> AsyncIterator[bytes]:
        """조각마다 WAV 하나. 첫 조각 전에 닿지 않으면 Piper 로 통째로 읽는다.

        중간에 끊기면 남은 부분은 읽지 않고 멈춘다. 이미 읽은 소리 뒤를 다른 목소리로 처음부터 다시 읽으면 더 어색하다.
        """
        sent = False
        try:
            async with self._client.stream("POST", self._stream_url, json={"text": text}) as response:
                response.raise_for_status()
                rate = int(response.headers.get("X-Sample-Rate", DEFAULT_SAMPLE_RATE))
                async for pcm in _frames(response.aiter_bytes()):
                    sent = True
                    yield _wav(pcm, rate)
        except (httpx.HTTPError, EOFError) as exc:
            if sent:
                logger.info(f"[Voice] qwen 조각 합성이 중간에 끊겨 남은 부분은 읽지 않는다: {exc!r}")
                return
            if self._fallback is None:
                raise
            logger.info(f"[Voice] qwen 합성 서버에 닿지 않아 Piper 로 읽는다: {exc!r}")
            audio = await self._fallback.synthesize(text, lang)
            if audio:
                yield audio


async def _frames(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """바이트 흐름을 조각으로 다시 묶는다. 길이 0 이 오기 전에 흐름이 끝나면 EOFError."""
    buf = b""
    async for data in chunks:
        buf += data
        while len(buf) >= FRAME_HEADER.size:
            (size,) = FRAME_HEADER.unpack_from(buf)
            if size == 0:
                return
            if len(buf) < FRAME_HEADER.size + size:
                break
            yield buf[FRAME_HEADER.size : FRAME_HEADER.size + size]
            buf = buf[FRAME_HEADER.size + size :]
    raise EOFError("합성 서버가 끝 표시 없이 닫았다")


def _wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _piper(model_path: str, noise_scale: float | None) -> TTSProvider | None:
    """대신 읽을 Piper. 모델이나 패키지가 없으면 None(대신 읽지 않는다)."""
    if not model_path:
        return None
    from jarvis.voice.providers.piper import PiperTTSProvider

    try:
        return PiperTTSProvider(model_path, noise_scale)
    except (ImportError, FileNotFoundError) as exc:
        logger.info(f"[Voice] qwen 의 대신 읽을 Piper 를 만들지 못했다: {exc}")
        return None
