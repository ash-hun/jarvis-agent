"""voice: load_phrases 는 목록에 있고 wav 도 있는 문구만 이름으로 찾고, load_phrase_texts 는 문구의 문장을 준다."""

import json
import pytest

from jarvis.voice.phrases import PHRASES_INDEX, load_phrase_texts, load_phrases


def write_index(root, entries):
    (root / PHRASES_INDEX).write_text(json.dumps(entries), "utf-8")


def test_load_phrases_lists_phrases_whose_wav_exists(tmp_path):
    (tmp_path / "wake_up.wav").write_bytes(b"RIFF")
    write_index(tmp_path, {
        "wake_up": {"audio": "phrases/wake_up.wav", "text": "At your service, sir."},
        "web_search": {"audio": "phrases/web_search.wav", "text": "Searching Reference."},
    })

    assert load_phrases(str(tmp_path)) == {"wake_up": tmp_path / "wake_up.wav"}


@pytest.mark.parametrize("case", ["empty_setting", "missing_index", "missing_dir", "non_wav"])
def test_load_phrases_returns_nothing_without_usable_phrases(tmp_path, case):
    if case == "non_wav":
        (tmp_path / "notes.txt").write_text("x")
        write_index(tmp_path, {"notes": {"audio": "phrases/notes.txt"}})
    root = {"empty_setting": "", "missing_dir": str(tmp_path / "nowhere")}.get(case, str(tmp_path))

    assert load_phrases(root) == {}


def test_load_phrase_texts_names_what_each_phrase_says(tmp_path):
    write_index(tmp_path, {
        "wake_up": {"audio": "phrases/wake_up.wav", "text": "At your service, sir."},
        "silent": {"audio": "phrases/silent.wav"},
    })

    assert load_phrase_texts(str(tmp_path)) == {"wake_up": "At your service, sir."}
    assert load_phrase_texts("") == {}
