"""JARVIS 목소리로 답 읽기: 무엇을 옮기는지, 옮긴 글을 어떻게 고르는지, 실패하면 원문으로 읽는지."""

import base64

from jarvis.voice.english import FALLBACK_LINE, clean_english, should_speak_english
from jarvis.voice.service import VoiceService
from jarvis.ui.web.ws_tasks import run_tts


def test_every_korean_jarvis_utterance_is_translated_but_not_other_agents():
    assert should_speak_english("내일 오전엔 운동하시면 됩니다.", "main")
    assert should_speak_english("회의 10분 전입니다.", "main")  # 🔔, filler 등 종류와 상관없이
    # KAREN 은 JARVIS 목소리로 읽지 않는다
    assert not should_speak_english("공고 두 건이에요.", "karen")
    # 이미 영어거나 빈 글은 옮길 것이 없다(영어는 그대로 영어 TTS 가 읽는다)
    assert not should_speak_english("At your service, sir.", "main")
    assert not should_speak_english("  ", "main")


def test_clean_english_strips_quotes_and_rejects_korean():
    assert clean_english(' "Very good, sir.\n  Exercise first." ') == "Very good, sir. Exercise first."
    assert clean_english("Sir, 운동하세요.") is None
    assert clean_english("") is None


class _WS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class _TTS:
    def __init__(self, audio):
        self.audio, self.read = audio, []

    async def synthesize(self, text, lang="ko"):
        self.read.append((text, lang))
        return self.audio


class _STT:
    async def transcribe(self, audio_bytes, sample_rate=16000):
        return ""


async def _speak(translated):
    ws, korean, english = _WS(), _TTS(b"ko"), _TTS(b"en")
    svc = VoiceService(stt=_STT(), tts=korean, english_tts=english)

    async def translate(text):
        return translated

    await run_tts(ws, svc, "내일 오전엔 운동하시면 됩니다.", "ko", 7, translate)
    return ws.sent[0], korean.read, english.read


async def test_translated_reply_is_read_by_the_english_voice_and_reports_what_it_read():
    sent, korean, english = await _speak("Exercise in the morning, sir.")
    assert english == [("Exercise in the morning, sir.", "en")] and korean == []
    assert sent["data"] == base64.b64encode(b"en").decode()
    assert (sent["text"], sent["id"]) == ("Exercise in the morning, sir.", 7)


async def test_failed_translation_reads_a_fixed_english_line_in_the_jarvis_voice():
    sent, korean, english = await _speak(None)
    assert english == [(FALLBACK_LINE, "en")] and korean == []
    assert sent["text"] == FALLBACK_LINE
