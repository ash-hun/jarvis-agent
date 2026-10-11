"""[voice] VoiceService.from_config 는 프로바이더마다 받은 생성 옵션을 그 팩토리에만 넘긴다."""

from jarvis.voice import registry
from jarvis.voice.protocol import STTProvider, TTSProvider
from jarvis.voice.service import VoiceService


def test_options_reach_only_their_factory(monkeypatch):
    seen: dict[str, dict[str, object]] = {}

    def stt_factory(**kwargs: object) -> STTProvider:
        seen["stt"] = kwargs
        return STTProvider()

    def tts_factory(**kwargs: object) -> TTSProvider:
        seen["tts"] = kwargs
        return TTSProvider()

    monkeypatch.setitem(registry._STT_REGISTRY, "fake", stt_factory)
    monkeypatch.setitem(registry._TTS_REGISTRY, "fake", tts_factory)

    VoiceService.from_config("fake", "fake", stt_options={"model_size": "tiny"}, tts_options={"voice": "f1"})

    assert seen == {"stt": {"model_size": "tiny"}, "tts": {"voice": "f1"}}


def test_no_options_is_empty_kwargs(monkeypatch):
    seen: list[dict[str, object]] = []
    monkeypatch.setitem(registry._STT_REGISTRY, "fake", lambda **kw: seen.append(kw) or STTProvider())
    VoiceService.from_config("fake", "browser")
    assert seen == [{}]
