"""notify: discord_voice 가 음성 채널에 있으면 읽고 없거나 실패하면 글로, 길면 잘라 읽고 글로도 남기는지 검증."""

import pytest
import asyncio

from jarvis.core.notify.discord_voice import (
    CUT_NOTE,
    SPEAK_MAX_CHARS,
    DiscordVoice,
    VoiceGateway,
    speech_of,
    voice_first,
)
from jarvis.voice.speech_text import speech_text


class Gateway(VoiceGateway):
    def __init__(self, channel=None, fail: bool = False) -> None:
        self.channel = channel
        self.fail = fail
        self.played: list[tuple[str, bytes]] = []

    async def channel_of(self, user_id):
        if self.fail:
            raise RuntimeError("discord down")
        return self.channel if user_id == 7 else None

    async def play(self, channel, wav):
        self.played.append((channel, wav))


def _run(gateway: VoiceGateway, payload: dict) -> tuple[list, list]:
    texts: list[dict] = []
    spoken: list[str] = []

    async def synthesize(text: str) -> bytes:
        spoken.append(text)
        return b"RIFF"

    async def text(p: dict) -> None:
        texts.append(p)

    notify = voice_first(DiscordVoice(gateway, 7, synthesize, speech_text), {"reminder", "proactive_message"}, text)
    asyncio.run(notify(payload))
    return spoken, texts


REMINDER = {"type": "reminder", "kind": "tool", "label": "오늘의 LH 공고", "agent_name": "K.A.R.E.N.",
            "text": "새 공고 1건 (서울). **행복주택** https://apply.lh.or.kr/x"}


def test_voice_first_reads_in_the_users_voice_channel_and_skips_text():
    gateway = Gateway(channel="거실")
    spoken, texts = _run(gateway, REMINDER)
    assert spoken == ["K.A.R.E.N. 오늘의 LH 공고. 새 공고 1건 (서울). 행복주택"]
    assert gateway.played == [("거실", b"RIFF")] and texts == []


@pytest.mark.parametrize(
    "gateway",
    [Gateway(channel=None), Gateway(fail=True), VoiceGateway()],
    ids=["not_in_voice", "discord_down", "base_gateway"],
)
def test_voice_first_falls_back_to_text(gateway):
    assert _run(gateway, REMINDER) == ([], [REMINDER])


def test_voice_first_sends_spoken_mirror_as_text_only():
    payload = {"type": "spoken", "agent_name": "J.A.R.V.I.S.", "text": "안녕하세요"}
    gateway = Gateway(channel="거실")
    assert _run(gateway, payload) == ([], [payload]) and gateway.played == []


def test_voice_first_cuts_long_alert_and_also_sends_text():
    payload = {**REMINDER, "text": "공고 " * 400}
    spoken, texts = _run(Gateway(channel="거실"), payload)
    assert spoken[0].endswith(CUT_NOTE) and len(spoken[0]) <= SPEAK_MAX_CHARS + len(CUT_NOTE) + 2
    assert texts == [payload]


def test_speech_of_does_not_repeat_the_agent_name():
    text, cut = speech_of({"type": "proactive_message", "agent_name": "K.A.R.E.N.", "text": "확인할까요?"}, speech_text)
    assert text.count("K.A.R.E.N.") == 1 and not cut
