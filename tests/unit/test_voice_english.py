"""voice: 무엇을 영어로 옮기는지, 옮긴 글을 어떻게 고르고 문장으로 나누는지."""

import pytest

from jarvis.voice.english import clean_english, split_sentences, should_speak_english


@pytest.mark.parametrize(
    ("text", "agent_id", "expected"),
    [
        ("내일 오전엔 운동하시면 됩니다.", "main", True),
        ("회의 10분 전입니다.", "main", True),
        # KAREN 은 JARVIS 목소리로 읽지 않는다
        ("공고 두 건이에요.", "karen", False),
        # 이미 영어면 영어 TTS 가 그대로 읽는다
        ("At your service, sir.", "main", False),
        ("  ", "main", False),
    ],
)
def test_should_speak_english_only_for_korean_jarvis_utterances(text, agent_id, expected):
    assert should_speak_english(text, agent_id) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (' "Very good, sir.\n  Exercise first." ', "Very good, sir. Exercise first."),
        ("Sir, 운동하세요.", None),
        ("", None),
    ],
)
def test_clean_english_strips_quotes_and_rejects_korean(raw, expected):
    assert clean_english(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Yes, sir. The meeting starts at three.  The weather is clear today.",
            ["Yes, sir.", "The meeting starts at three.", "The weather is clear today."],
        ),
        # 짧은 뒤 조각이 따로 읽히면 끊겨 들린다
        ("You have three notices to review today. Shall I?", ["You have three notices to review today. Shall I?"]),
        ("Very good, sir", ["Very good, sir"]),
    ],
)
def test_split_sentences_keeps_short_tails_with_the_sentence_before(text, expected):
    assert split_sentences(text) == expected
