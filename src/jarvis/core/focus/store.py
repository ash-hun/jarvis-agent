"""[core] Focus 작업을 ~/.jarvis/focus/ 아래 파일로 남기고 세션당 활성 작업 하나를 보증한다."""

import os
import json
from typing import Any
from pathlib import Path

from jarvis.core.focus.types import FocusState

ACTIVE_DIR = "active"
STATE_FILE = "state.json"
LOG_FILE = "log.md"
REFERENCE_FILE = "references.md"
ANALYSIS_FILE = "analysis.jsonl"


class FocusStore:
    """작업마다 폴더 하나(state.json, log.md, references.md, analysis.jsonl). 활성 표시는 active/<session_id>."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).expanduser()
        (self._root / ACTIVE_DIR).mkdir(parents=True, exist_ok=True)

    def claim(self, session_id: str, task_id: str) -> bool:
        """세션의 활성 작업으로 표시한다. 이미 있으면 False. O_EXCL 이라 동시에 두 번 불러도 하나만 이긴다."""
        try:
            fd = os.open(self._active(session_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as f:
            f.write(task_id)
        return True

    def release(self, session_id: str) -> None:
        self._active(session_id).unlink(missing_ok=True)

    def active_task(self, session_id: str) -> str | None:
        path = self._active(session_id)
        return path.read_text().strip() or None if path.exists() else None

    def save_state(self, state: FocusState) -> None:
        self._write(self._dir(state.task_id) / STATE_FILE, json.dumps(state.to_json(), ensure_ascii=False, indent=2))

    def load_state(self, task_id: str) -> FocusState | None:
        path = self._dir(task_id) / STATE_FILE
        return FocusState.from_json(json.loads(path.read_text())) if path.exists() else None

    def append_log(self, task_id: str, entry: str) -> None:
        self._append(self._dir(task_id) / LOG_FILE, entry.strip() + "\n\n")

    def read_log(self, task_id: str) -> str:
        return self._read(self._dir(task_id) / LOG_FILE)

    def append_reference(self, task_id: str, entry: str) -> None:
        self._append(self._dir(task_id) / REFERENCE_FILE, entry.strip() + "\n\n")

    def read_references(self, task_id: str) -> str:
        return self._read(self._dir(task_id) / REFERENCE_FILE)

    def append_analysis(self, task_id: str, analysis: dict[str, Any]) -> None:
        self._append(self._dir(task_id) / ANALYSIS_FILE, json.dumps(analysis, ensure_ascii=False) + "\n")

    def last_analysis(self, task_id: str) -> dict[str, Any] | None:
        lines = self._read(self._dir(task_id) / ANALYSIS_FILE).splitlines()
        return json.loads(lines[-1]) if lines else None

    def log_path(self, task_id: str) -> Path:
        return self._dir(task_id) / LOG_FILE

    def _active(self, session_id: str) -> Path:
        return self._root / ACTIVE_DIR / session_id

    def _dir(self, task_id: str) -> Path:
        path = self._root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _write(path: Path, text: str) -> None:
        # 쓰다 죽어도 이전 상태가 남도록 임시 파일에 쓰고 바꿔 끼운다
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text)
        tmp.replace(path)

    @staticmethod
    def _append(path: Path, text: str) -> None:
        with path.open("a") as f:
            f.write(text)

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text() if path.exists() else ""
