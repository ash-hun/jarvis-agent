"""[voice] 미리 녹음한 읽기 문구 폴더(phrases.json 과 wav)에서 재생할 수 있는 문구를 이름으로 찾는다."""

import json
from pathlib import Path

PHRASES_INDEX = "phrases.json"


def load_phrases(phrases_dir: str) -> dict[str, Path]:
    """문구 이름 → wav 경로. 목록에 있고 파일도 있는 것만. 폴더를 비웠거나 목록이 없으면 빈 dict."""
    root, entries = _index(phrases_dir)
    found: dict[str, Path] = {}
    for name, entry in entries.items():
        # audio 는 학습 폴더 기준 상대 경로("phrases/wake_up.wav")라 파일 이름만 쓴다
        wav = root / Path(str(entry.get("audio", ""))).name
        if wav.suffix == ".wav" and wav.is_file():
            found[name] = wav
    return found


def load_phrase_texts(phrases_dir: str) -> dict[str, str]:
    """문구 이름 → 읽는 문장. 화면이 문구를 재생했다고 알리면 이 글로 밖에 알린다."""
    _, entries = _index(phrases_dir)
    return {name: str(entry.get("text", "")) for name, entry in entries.items() if entry.get("text")}


def _index(phrases_dir: str) -> tuple[Path, dict[str, dict[str, object]]]:
    if not phrases_dir:
        return Path(), {}
    root = Path(phrases_dir).expanduser()
    index = root / PHRASES_INDEX
    if not index.is_file():
        return root, {}
    entries: dict[str, dict[str, object]] = json.loads(index.read_text("utf-8"))
    return root, entries
