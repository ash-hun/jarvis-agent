"""TUI 음성 컨트롤러 — TuiVoiceController + 시스템 오디오 백엔드 테스트."""
from __future__ import annotations

import pytest

from jarvis.ui.tui.voice import (
    _PLAYERS,
    TuiVoiceController,
    VoiceUnavailable,
    _detect,
    play_wav_via_system,
    record_wav_via_system,
)

# ── fake 프로바이더/서비스 ──────────────────────────────────────────────────────

class _FakeSTT:
    async def transcribe(self, audio_bytes, sample_rate=16000):
        return f"전사:{audio_bytes.decode()}"


class _FakeTTS:
    def __init__(self, audio=b"WAV"):
        self._audio = audio

    async def synthesize(self, text, lang="ko"):
        return self._audio


def _service(stt=None, tts=None):
    from jarvis.voice.service import VoiceService
    return VoiceService(stt=stt or _FakeSTT(), tts=tts or _FakeTTS())


# ── speak ──────────────────────────────────────────────────────────────────────

class TestSpeak:
    async def test_speak_plays_audio(self):
        played = []

        async def fake_player(audio):
            played.append(audio)

        ctrl = TuiVoiceController(_service(), player=fake_player)
        result = await ctrl.speak("안녕하세요")

        assert result is True
        assert played == [b"WAV"]

    async def test_speak_empty_text_returns_false(self):
        played = []

        async def fake_player(audio):
            played.append(audio)

        ctrl = TuiVoiceController(_service(), player=fake_player)
        assert await ctrl.speak("   ") is False
        assert played == []

    async def test_speak_no_audio_returns_false(self):
        """browser TTS는 빈 bytes → 재생할 게 없음."""
        played = []

        async def fake_player(audio):
            played.append(audio)

        ctrl = TuiVoiceController(_service(tts=_FakeTTS(audio=b"")), player=fake_player)
        assert await ctrl.speak("안녕") is False
        assert played == []


# ── listen ───────────────────────────────────────────────────────────────────

class TestListen:
    async def test_listen_records_and_transcribes(self):
        async def fake_recorder(seconds):
            return b"audio"

        ctrl = TuiVoiceController(_service(), recorder=fake_recorder)
        assert await ctrl.listen(3.0) == "전사:audio"

    async def test_listen_empty_audio_returns_empty(self):
        async def fake_recorder(seconds):
            return b""

        ctrl = TuiVoiceController(_service(), recorder=fake_recorder)
        assert await ctrl.listen() == ""

    async def test_listen_passes_seconds(self):
        seen = []

        async def fake_recorder(seconds):
            seen.append(seconds)
            return b"x"

        ctrl = TuiVoiceController(_service(), recorder=fake_recorder)
        await ctrl.listen(7.5)
        assert seen == [7.5]


# ── 가용성 플래그 ────────────────────────────────────────────────────────────────

class TestAvailability:
    def test_browser_providers_disable(self):
        from jarvis.voice.service import VoiceService

        svc = VoiceService.from_config(stt_provider="browser", tts_provider="browser")
        ctrl = TuiVoiceController(svc)
        assert ctrl.can_speak is False
        assert ctrl.can_listen is False

    def test_custom_providers_enable(self):
        ctrl = TuiVoiceController(_service())
        assert ctrl.can_speak is True
        assert ctrl.can_listen is True


# ── 시스템 오디오 백엔드 ──────────────────────────────────────────────────────────

class TestSystemBackends:
    def test_detect_picks_first_available(self, monkeypatch):
        # aplay만 설치된 환경 시뮬레이션
        monkeypatch.setattr(
            "jarvis.ui.tui.voice.shutil.which",
            lambda name: "/usr/bin/aplay" if name == "aplay" else None,
        )
        build = _detect(_PLAYERS)
        assert build is not None
        assert build("x.wav")[0] == "aplay"

    def test_detect_returns_none_when_nothing(self, monkeypatch):
        monkeypatch.setattr("jarvis.ui.tui.voice.shutil.which", lambda name: None)
        assert _detect(_PLAYERS) is None

    async def test_play_raises_without_player_tool(self, monkeypatch):
        monkeypatch.setattr("jarvis.ui.tui.voice.shutil.which", lambda name: None)
        with pytest.raises(VoiceUnavailable, match="재생 도구"):
            await play_wav_via_system(b"WAV")

    async def test_record_raises_without_recorder_tool(self, monkeypatch):
        monkeypatch.setattr("jarvis.ui.tui.voice.shutil.which", lambda name: None)
        with pytest.raises(VoiceUnavailable, match="녹음 도구"):
            await record_wav_via_system(3.0)
