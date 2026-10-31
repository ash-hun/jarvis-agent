"""voice: TUI 음성 컨트롤러의 읽기, 듣기, 가용성과 시스템 오디오 도구 선택(ui/tui/voice.py)."""

import pytest

from jarvis.ui.tui.voice import TuiVoiceController, VoiceUnavailable, play_wav_via_system, record_wav_via_system
from jarvis.voice.voice_service import VoiceService


class _FakeSTT:
    async def transcribe(self, audio_bytes, sample_rate=16000):
        return f"전사:{audio_bytes.decode()}"


class _FakeTTS:
    def __init__(self, audio=b"WAV"):
        self._audio = audio

    async def synthesize(self, text, lang="ko"):
        return self._audio


def _service(tts=None):
    return VoiceService(stt=_FakeSTT(), tts=tts or _FakeTTS())


def _player(played):
    async def play(audio):
        played.append(audio)

    return play


async def test_speak_plays_audio():
    played = []
    ctrl = TuiVoiceController(_service(), player=_player(played))

    result = await ctrl.speak("안녕하세요")

    assert result is True
    assert played == [b"WAV"]


# browser TTS 는 빈 bytes 를 내 재생할 것이 없다
@pytest.mark.parametrize(("text", "audio"), [("   ", b"WAV"), ("안녕", b"")])
async def test_speak_returns_false_without_text_or_audio(text, audio):
    played = []
    ctrl = TuiVoiceController(_service(tts=_FakeTTS(audio=audio)), player=_player(played))

    assert await ctrl.speak(text) is False
    assert played == []


async def test_listen_records_for_given_seconds_and_transcribes():
    seen = []

    async def fake_recorder(seconds):
        seen.append(seconds)
        return b"audio"

    ctrl = TuiVoiceController(_service(), recorder=fake_recorder)

    assert await ctrl.listen(7.5) == "전사:audio"
    assert seen == [7.5]


async def test_listen_empty_audio_returns_empty():
    async def fake_recorder(seconds):
        return b""

    ctrl = TuiVoiceController(_service(), recorder=fake_recorder)

    assert await ctrl.listen() == ""


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (VoiceService.from_config(stt_provider="browser", tts_provider="browser"), False),
        (_service(), True),
    ],
)
def test_can_speak_and_listen_only_with_server_providers(service, expected):
    ctrl = TuiVoiceController(service)

    assert ctrl.can_speak is expected
    assert ctrl.can_listen is expected


async def test_play_wav_via_system_uses_the_first_available_player(monkeypatch):
    argv = []

    class _Proc:
        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kwargs):
        argv.extend(cmd)
        return _Proc()

    monkeypatch.setattr(
        "jarvis.ui.tui.voice.shutil.which",
        lambda name: "/usr/bin/aplay" if name == "aplay" else None,
    )
    monkeypatch.setattr("jarvis.ui.tui.voice.asyncio.create_subprocess_exec", fake_exec)

    await play_wav_via_system(b"WAV")

    assert argv[0] == "aplay"


@pytest.mark.parametrize(
    ("run", "message"),
    [(lambda: play_wav_via_system(b"WAV"), "재생 도구"), (lambda: record_wav_via_system(3.0), "녹음 도구")],
)
async def test_system_audio_raises_without_a_tool(monkeypatch, run, message):
    monkeypatch.setattr("jarvis.ui.tui.voice.shutil.which", lambda name: None)

    with pytest.raises(VoiceUnavailable, match=message):
        await run()
