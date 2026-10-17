"""load_phrases: 목록에 있고 wav 도 있는 문구만 이름으로 찾는다."""

import json

from jarvis.voice.phrases import PHRASES_INDEX, load_phrases


def write_index(root, entries):
    (root / PHRASES_INDEX).write_text(json.dumps(entries), "utf-8")


def test_lists_phrases_whose_wav_exists(tmp_path):
    (tmp_path / "wake_up.wav").write_bytes(b"RIFF")
    write_index(tmp_path, {
        "wake_up": {"audio": "phrases/wake_up.wav", "text": "At your service, sir."},
        "web_search": {"audio": "phrases/web_search.wav", "text": "Searching Reference."},
    })

    assert load_phrases(str(tmp_path)) == {"wake_up": tmp_path / "wake_up.wav"}


def test_empty_setting_or_missing_index_means_no_phrases(tmp_path):
    assert load_phrases("") == {}
    assert load_phrases(str(tmp_path)) == {}
    assert load_phrases(str(tmp_path / "nowhere")) == {}


def test_non_wav_audio_is_skipped(tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    write_index(tmp_path, {"notes": {"audio": "phrases/notes.txt"}})

    assert load_phrases(str(tmp_path)) == {}
