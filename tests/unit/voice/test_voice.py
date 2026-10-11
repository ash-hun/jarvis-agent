"""Voice 서브시스템: 레지스트리, VoiceService, 서버 STT 핸들러 테스트."""
from __future__ import annotations

import base64

import pytest

# ── 레지스트리 ─────────────────────────────────────────────────────────────────

class TestVoiceRegistry:
    def test_make_stt_browser(self):
        from jarvis.voice.providers.browser import BrowserSTTProvider
        from jarvis.voice.registry import make_stt

        assert isinstance(make_stt("browser"), BrowserSTTProvider)

    def test_make_tts_browser(self):
        from jarvis.voice.providers.browser import BrowserTTSProvider
        from jarvis.voice.registry import make_tts

        assert isinstance(make_tts("browser"), BrowserTTSProvider)

    def test_make_stt_unknown_raises(self):
        from jarvis.voice.registry import make_stt

        with pytest.raises(ValueError, match="알 수 없는 STT"):
            make_stt("nonexistent")

    def test_make_tts_unknown_raises(self):
        from jarvis.voice.registry import make_tts

        with pytest.raises(ValueError, match="알 수 없는 TTS"):
            make_tts("nonexistent")

    def test_register_custom_stt(self):
        from jarvis.voice.registry import make_stt, register_stt

        class FakeSTT:
            async def transcribe(self, audio_bytes, sample_rate=16000):
                return "fake"

        register_stt("fake-stt", lambda **kw: FakeSTT())
        assert isinstance(make_stt("fake-stt"), FakeSTT)


# ── BrowserSTTProvider 동작 명세 ────────────────────────────────────────────────

class TestBrowserProviders:
    async def test_browser_stt_returns_empty(self):
        """브라우저 STT는 서버에서 전사하지 않음. 클라이언트 Web Speech API 전용.

        방어적으로 호출돼도 빈 문자열을 돌려 메인 흐름을 막지 않는다(TTS와 동일 규약).
        """
        from jarvis.voice.providers.browser import BrowserSTTProvider

        assert await BrowserSTTProvider().transcribe(b"audio") == ""

    async def test_browser_tts_returns_empty(self):
        """빈 bytes → 클라이언트가 browser TTS fallback 사용."""
        from jarvis.voice.providers.browser import BrowserTTSProvider

        assert await BrowserTTSProvider().synthesize("안녕") == b""


# ── VoiceService ───────────────────────────────────────────────────────────────

class _FakeSTT:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio_bytes, sample_rate=16000):
        self.calls.append((audio_bytes, sample_rate))
        return "전사된 텍스트"


class _FakeTTS:
    async def synthesize(self, text, lang="ko"):
        return b"WAVDATA"


class TestVoiceService:
    async def test_transcribe_delegates(self):
        from jarvis.voice.service import VoiceService

        stt = _FakeSTT()
        svc = VoiceService(stt=stt, tts=_FakeTTS())
        result = await svc.transcribe(b"rawaudio", sample_rate=8000)
        assert result == "전사된 텍스트"
        assert stt.calls == [(b"rawaudio", 8000)]

    async def test_synthesize_delegates(self):
        from jarvis.voice.service import VoiceService

        svc = VoiceService(stt=_FakeSTT(), tts=_FakeTTS())
        assert await svc.synthesize("안녕") == b"WAVDATA"

    def test_stt_is_browser_true(self):
        from jarvis.voice.service import VoiceService

        svc = VoiceService.from_config(stt_provider="browser", tts_provider="browser")
        assert svc.stt_is_browser is True
        assert svc.tts_is_browser is True

    def test_stt_is_browser_false_for_custom(self):
        from jarvis.voice.service import VoiceService

        svc = VoiceService(stt=_FakeSTT(), tts=_FakeTTS())
        assert svc.stt_is_browser is False
        assert svc.tts_is_browser is False


# ── 서버 STT 핸들러 (_run_stt) ──────────────────────────────────────────────────

class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class TestRunStt:
    async def test_transcribes_and_sends_result(self):
        from jarvis.ui.web.ws_tasks import run_stt as _run_stt
        from jarvis.voice.service import VoiceService

        ws = _FakeWS()
        svc = VoiceService(stt=_FakeSTT(), tts=_FakeTTS())
        audio_b64 = base64.b64encode(b"rawaudio").decode()

        await _run_stt(ws, svc, audio_b64, 16000)

        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "voice_stt_result"
        assert ws.sent[0]["text"] == "전사된 텍스트"
        assert "error" not in ws.sent[0]

    async def test_error_path_sends_error(self):
        from jarvis.ui.web.ws_tasks import run_stt as _run_stt

        class _BoomSTT:
            async def transcribe(self, audio_bytes, sample_rate=16000):
                raise RuntimeError("whisper 실패")

        from jarvis.voice.service import VoiceService

        ws = _FakeWS()
        svc = VoiceService(stt=_BoomSTT(), tts=_FakeTTS())
        audio_b64 = base64.b64encode(b"x").decode()

        await _run_stt(ws, svc, audio_b64, 16000)

        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "voice_stt_result"
        assert ws.sent[0]["text"] == ""
        assert "whisper 실패" in ws.sent[0]["error"]

    async def test_invalid_base64_sends_error(self):
        from jarvis.ui.web.ws_tasks import run_stt as _run_stt
        from jarvis.voice.service import VoiceService

        ws = _FakeWS()
        svc = VoiceService(stt=_FakeSTT(), tts=_FakeTTS())

        await _run_stt(ws, svc, "!!!not-base64!!!", 16000)

        assert ws.sent[0]["type"] == "voice_stt_result"
        assert ws.sent[0]["text"] == ""
        assert "error" in ws.sent[0]
