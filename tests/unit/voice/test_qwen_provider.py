"""qwen TTS: Mac 합성 서버의 WAV 를 그대로 쓰고, 닿지 않거나 실패하면 Piper 로 읽는다."""

import httpx
import pytest

from jarvis.voice.providers.qwen import QwenTTSProvider
from jarvis.voice.protocol import TTSProvider
from jarvis.config import VoiceConfig


class Piper(TTSProvider):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        self.texts.append(text)
        return b"piper"


def provider(handler, fallback=None) -> QwenTTSProvider:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return QwenTTSProvider("http://host:8770/", fallback=fallback, client=client)


async def test_server_wav_is_returned_as_is():
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        assert request.url.path == "/tts"
        return httpx.Response(200, content=b"RIFFqwen")

    piper = Piper()
    assert await provider(handler, piper).synthesize("Yes, sir?", "en") == b"RIFFqwen"
    assert seen == [b'{"text":"Yes, sir?"}'] and piper.texts == []


@pytest.mark.parametrize("failure", ["refused", "500"])
async def test_unreachable_or_failing_server_falls_back_to_piper(failure):
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "refused":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(500)

    piper = Piper()
    assert await provider(handler, piper).synthesize("Yes, sir?", "en") == b"piper"
    assert piper.texts == ["Yes, sir?"]


async def test_without_piper_the_error_is_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(httpx.ConnectError):
        await provider(handler).synthesize("Yes, sir?", "en")


def test_missing_piper_model_means_no_fallback():
    assert QwenTTSProvider("http://host:8770", piper_model="/nope/voice.onnx")._fallback is None


def test_config_passes_the_server_url_and_the_piper_fallback():
    cfg = VoiceConfig(english_tts_provider="qwen", piper_model="/m/voice.onnx")
    assert cfg.english_tts_options() == {
        "url": "http://host.docker.internal:8770", "piper_model": "/m/voice.onnx", "noise_scale": 0.4,
    }
