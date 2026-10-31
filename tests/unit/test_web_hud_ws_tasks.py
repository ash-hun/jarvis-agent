"""web_hud 의 ws_tasks: focus 안내, 🔔 피드백 한 번 학습, 서버 STT 결과와 영어 번역 TTS 스트리밍."""

import base64
import pytest
from typing import Any

from jarvis.ui.web.ws_tasks import run_focus, first_feedback, run_stt, run_tts
from jarvis.voice.voice_protocol import Transcript, TTSProvider
from jarvis.core.focus.focus_types import parse_command
from jarvis.voice.voice_service import VoiceService
from jarvis.voice.english import FALLBACK_LINE


class FakeAdapter:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def show_error(self, message: str) -> None:
        self.sent.append({"type": "error", "message": message})


class FakeSession:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def prompt(self, text: str, credentials: dict[str, str]) -> None:
        self.prompts.append(text)


class FakeFocus:
    def __init__(self, follow_up: str | None) -> None:
        self._follow_up = follow_up

    async def handle(self, command: Any, session: Any) -> tuple[str, str | None]:
        return "[Focus] 안내", self._follow_up


@pytest.mark.parametrize(
    ("follow_up", "continues", "prompts"), [("회의 아젠다", True, ["회의 아젠다"]), (None, False, [])]
)
async def test_run_focus_agent_end_says_whether_main_agent_continues(
    follow_up: str | None, continues: bool, prompts: list[str]
) -> None:
    adapter, session = FakeAdapter(), FakeSession()
    command = parse_command("/focus 회의 아젠다")
    assert command is not None

    await run_focus(session, adapter, FakeFocus(follow_up), command, {})  # type: ignore[arg-type]

    assert adapter.sent == [
        {"type": "agent_start"},
        {"type": "stream_delta", "text": "[Focus] 안내"},
        {"type": "agent_end", "continues": continues},
    ]
    assert session.prompts == prompts


def test_first_feedback_true_once_per_message_id():
    seen: set[str] = set()

    results = [first_feedback(seen, "m1"), first_feedback(seen, "m1"), first_feedback(seen, "m2")]

    assert results == [True, False, True]
    assert seen == {"m1", "m2"}


@pytest.mark.parametrize("message_id", [None, "", 7, ["m1"]])
def test_first_feedback_without_string_id_always_true_and_not_recorded(message_id):
    seen: set[str] = set()

    results = [first_feedback(seen, message_id), first_feedback(seen, message_id)]

    assert results == [True, True]
    assert seen == set()


class _WS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


class _TTS(TTSProvider):
    def __init__(self, audio):
        self.audio, self.read = audio, []

    async def synthesize(self, text, lang="ko"):
        self.read.append((text, lang))
        return self.audio


class _STT:
    def __init__(self, text=""):
        self.text = text

    async def transcribe(self, audio_bytes, sample_rate=16000):
        return self.text


class _BoomSTT:
    async def transcribe(self, audio_bytes, sample_rate=16000):
        raise RuntimeError("whisper 실패")


class _ScoredSTT:
    def __init__(self, transcript):
        self.transcript = transcript

    async def transcribe_scored(self, audio_bytes, sample_rate=16000):
        return self.transcript


async def _speak(translated, stream=False):
    ws, korean, english = _WS(), _TTS(b"ko"), _TTS(b"en")
    svc = VoiceService(stt=_STT(), tts=korean, english_tts=english)

    async def translate(text):
        return translated

    await run_tts(ws, svc, "내일 오전엔 운동하시면 됩니다.", "ko", 7, translate, stream)
    return (ws.sent if stream else ws.sent[0]), korean.read, english.read


async def _hear(transcript, agent_id="main"):
    ws, korean, english = _WS(), _TTS(b"ko-wav"), _TTS(b"en-wav")
    svc = VoiceService(stt=_ScoredSTT(transcript), tts=korean, english_tts=english)

    await run_stt(ws, svc, base64.b64encode(b"x").decode(), 16000, agent_id)

    return ws.sent, [t for t, _ in korean.read], [t for t, _ in english.read]


async def test_run_stt_sends_the_transcript():
    ws = _WS()
    svc = VoiceService(stt=_STT("전사된 텍스트"), tts=_TTS(b""))

    await run_stt(ws, svc, base64.b64encode(b"rawaudio").decode(), 16000)

    assert ws.sent == [{"type": "voice_stt_result", "text": "전사된 텍스트"}]


@pytest.mark.parametrize(
    ("stt", "audio_b64", "error_part"),
    [
        (_BoomSTT(), base64.b64encode(b"x").decode(), "whisper 실패"),
        (_STT("전사된 텍스트"), "!!!not-base64!!!", ""),
    ],
)
async def test_run_stt_failure_sends_empty_text_with_error(stt, audio_b64, error_part):
    ws = _WS()
    svc = VoiceService(stt=stt, tts=_TTS(b""))

    await run_stt(ws, svc, audio_b64, 16000)

    assert len(ws.sent) == 1
    assert (ws.sent[0]["type"], ws.sent[0]["text"]) == ("voice_stt_result", "")
    assert error_part in ws.sent[0]["error"]


async def test_run_stt_unsure_transcript_is_not_passed_on_and_jarvis_asks_again_in_english():
    sent, korean, english = await _hear(Transcript("자비스 외골", avg_logprob=-1.4))

    assert sent[0] == {"type": "voice_stt_result", "text": "", "unclear": True, "heard": "자비스 외골"}
    # id 가 없어야 화면이 바로 재생한다
    assert english == ["I'm sorry, sir. I didn't catch that."] and korean == []
    assert sent[1]["type"] == "voice_tts_audio" and sent[1]["id"] is None


async def test_run_stt_unsure_transcript_for_other_agents_asks_again_in_korean():
    _sent, korean, english = await _hear(Transcript("", no_speech_prob=0.9), agent_id="karen")

    assert korean == ["잘 못 들었어요. 한 번 더 말씀해 주세요."] and english == []


async def test_run_stt_confident_transcript_goes_through_untouched():
    sent, korean, english = await _hear(Transcript("지금 몇 시야", no_speech_prob=0.1, avg_logprob=-0.3))

    assert sent == [{"type": "voice_stt_result", "text": "지금 몇 시야"}]
    assert korean == english == []


async def test_run_tts_translated_reply_is_read_by_the_english_voice_and_reports_what_it_read():
    sent, korean, english = await _speak("Exercise in the morning, sir.")

    assert english == [("Exercise in the morning, sir.", "en")] and korean == []
    assert sent["data"] == base64.b64encode(b"en").decode()
    assert (sent["text"], sent["id"]) == ("Exercise in the morning, sir.", 7)


async def test_run_tts_unstreamed_reply_keeps_the_single_message_shape():
    sent, _korean, _english = await _speak("You have a meeting at three today. The weather is clear and mild.")

    assert "more" not in sent and sent["text"].endswith("mild.")


async def test_run_tts_failed_translation_reads_a_fixed_english_line_in_the_jarvis_voice():
    sent, korean, english = await _speak(None)

    assert english == [(FALLBACK_LINE, "en")] and korean == []
    assert sent["text"] == FALLBACK_LINE


async def test_run_tts_stream_sends_sentence_by_sentence_and_closes_with_an_empty_end():
    sent, _korean, english = await _speak("You have a meeting at three today. The weather is clear and mild.", True)

    assert [t for t, _ in english] == ["You have a meeting at three today.", "The weather is clear and mild."]
    assert [(m["text"], bool(m["data"]), m["more"], m["id"]) for m in sent] == [
        ("You have a meeting at three today.", True, True, 7),
        ("The weather is clear and mild.", True, True, 7),
        ("", False, False, 7),
    ]


async def test_run_tts_stream_without_any_sound_lets_the_browser_read_it():
    ws = _WS()
    svc = VoiceService(stt=_STT(), tts=_TTS(b""), english_tts=_TTS(b""))

    await run_tts(ws, svc, "Very good, sir.", "en", 7, None, True)

    assert ws.sent == [{"type": "voice_tts_audio", "data": "", "text": "Very good, sir.", "id": 7, "more": False}]
