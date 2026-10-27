"""[voice] Mac 호스트의 Qwen3-TTS 합성 서버(services/qwen_tts)를 부르고, 닿지 않으면 Piper 로 읽는 영어 TTS."""

import httpx

from jarvis.voice.protocol import DEFAULT_LANG, TTSProvider
from jarvis.common.logger import get_logger

# 서버가 꺼져 있으면 바로 Piper 로 넘어가도록 연결은 짧게, 합성(긴 문장 3초쯤)은 넉넉히 기다린다
CONNECT_TIMEOUT_SEC = 1.0
SYNTH_TIMEOUT_SEC = 20.0

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
