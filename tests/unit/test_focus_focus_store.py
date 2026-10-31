"""focus 기능의 FocusStore: 세션당 활성 작업 하나 보증과 파일 기록 복원."""

from pathlib import Path

from jarvis.core.focus.focus_types import FocusState, FocusStep
from jarvis.core.focus.focus_store import FocusStore


def test_claim_is_exclusive_per_session(tmp_path: Path) -> None:
    store = FocusStore(str(tmp_path))

    claims = [store.claim("s1", "t1"), store.claim("s1", "t2"), store.claim("s2", "t3")]

    assert claims == [True, False, True]
    assert store.active_task("s1") == "t1"


def test_release_twice_frees_session(tmp_path: Path) -> None:
    store = FocusStore(str(tmp_path))
    store.claim("s1", "t1")

    store.release("s1")
    store.release("s1")

    assert store.active_task("s1") is None
    assert store.claim("s1", "t2") is True


def test_records_survive_reopen(tmp_path: Path) -> None:
    store = FocusStore(str(tmp_path))
    state = FocusState("t1", "s1", "작업", 1.0, (FocusStep("a"),))
    store.save_state(state)
    store.append_log("t1", "### 기록 1")
    store.append_log("t1", "### 기록 2")
    store.append_reference("t1", "## 조사")
    store.append_analysis("t1", {"purpose": ["a"]})
    store.append_analysis("t1", {"purpose": ["b"]})

    reopened = FocusStore(str(tmp_path))
    assert reopened.load_state("t1") == state
    assert reopened.read_log("t1") == "### 기록 1\n\n### 기록 2\n\n"
    assert reopened.read_references("t1") == "## 조사\n\n"
    assert reopened.last_analysis("t1") == {"purpose": ["b"]}
    assert reopened.load_state("none") is None
    assert reopened.last_analysis("none") is None
