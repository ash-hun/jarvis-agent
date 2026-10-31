"""voice: VoiceService 의 전사 위임, 영어 문장 라우팅, 브라우저 판정, from_config 옵션 전달."""

import pytest

from jarvis.voice.voice_protocol import STTProvider, TTSProvider
from jarvis.voice.voice_service import VoiceService, is_english
from jarvis.voice import voice_registry


class _FakeSTT:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio_bytes, sample_rate=16000):
        self.calls.append((audio_bytes, sample_rate))
        return "전사된 텍스트"


class _Recorder(TTSProvider):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, lang: str = "ko") -> bytes:
        self.calls.append((text, lang))
        return self.name.encode()


async def test_transcribe_delegates_audio_and_rate_to_stt():
    stt = _FakeSTT()
    svc = VoiceService(stt=stt, tts=TTSProvider())

    result = await svc.transcribe(b"rawaudio", sample_rate=8000)

    assert result == "전사된 텍스트"
    assert stt.calls == [(b"rawaudio", 8000)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Good evening, sir. All systems are online.", True),
        ("안녕하세요, 오늘 일정 알려드릴게요.", False),
        ("오늘 PR 두 개 머지했어요.", False),
        ("12:30", False),
        ("こんにちは", False),
    ],
)
def test_is_english_only_for_latin_only_sentences(text: str, expected: bool) -> None:
    assert is_english(text) is expected


@pytest.mark.parametrize(
    ("with_english", "text", "lang", "expected_audio", "expected_call"),
    [
        (True, "Shall I render the suit, sir?", "ko", b"english", ("english", ("Shall I render the suit, sir?", "en"))),
        (True, "수트를 렌더링할까요?", "ko", b"default", ("default", ("수트를 렌더링할까요?", "ko"))),
        (False, "Hello there.", "ko", b"default", ("default", ("Hello there.", "ko"))),
        (False, "안녕", "ko", b"default", ("default", ("안녕", "ko"))),
    ],
)
async def test_synthesize_routes_english_text_to_english_tts_only_when_present(
    with_english, text, lang, expected_audio, expected_call
):
    providers = {"default": _Recorder("default"), "english": _Recorder("english")}
    english = providers["english"] if with_english else None
    service = VoiceService(STTProvider(), providers["default"], english_tts=english)

    audio = await service.synthesize(text, lang)

    name, call = expected_call
    assert audio == expected_audio
    assert providers[name].calls == [call]
    assert all(p.calls == [] for n, p in providers.items() if n != name)


def test_browser_flags_true_for_browser_providers_from_config():
    svc = VoiceService.from_config(stt_provider="browser", tts_provider="browser")

    assert svc.stt_is_browser is True and svc.tts_is_browser is True


@pytest.mark.parametrize(("stt", "tts"), [(_FakeSTT(), _Recorder("x")), (STTProvider(), TTSProvider())])
def test_browser_flags_false_for_non_browser_providers_including_bare_base(stt, tts):
    service = VoiceService(stt=stt, tts=tts)

    assert service.stt_is_browser is False and service.tts_is_browser is False


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            {"stt_options": {"model_size": "tiny"}, "tts_options": {"voice": "f1"}},
            {"stt": {"model_size": "tiny"}, "tts": {"voice": "f1"}},
        ),
        ({}, {"stt": {}, "tts": {}}),
    ],
)
def test_from_config_passes_options_only_to_their_factory(monkeypatch, options, expected):
    seen: dict[str, dict[str, object]] = {}

    def stt_factory(**kwargs: object) -> STTProvider:
        seen["stt"] = kwargs
        return STTProvider()

    def tts_factory(**kwargs: object) -> TTSProvider:
        seen["tts"] = kwargs
        return TTSProvider()

    # register_stt 는 전역 레지스트리에 영구히 남아 다른 테스트로 샌다
    monkeypatch.setitem(voice_registry._STT_REGISTRY, "fake", stt_factory)
    monkeypatch.setitem(voice_registry._TTS_REGISTRY, "fake", tts_factory)

    VoiceService.from_config("fake", "fake", **options)

    assert seen == expected
