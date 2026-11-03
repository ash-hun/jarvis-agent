"""[tests] ProactiveBench 라벨 대응, 이벤트 변환, 층화 표본, 꼭짓점 점수와 실행을 검증한다."""

import pytest
from typing import Any
from pathlib import Path
from scripts.experiments import proactivebench_vertex as vertex

from jarvis.core.proactive.eval.proactivebench import (
    BenchEvent,
    format_events,
    scene_events,
    stratified_sample,
    to_label,
    to_thought_request,
    vertex_score,
)
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK


def _step(time: str, event: str, candidates: list[str], status: bool) -> dict[str, Any]:
    return {"observation": {"time": time, "event": event}, "agent_response": {"candidate_task": candidates},
            "task_status": status}


def _trace() -> list[dict[str, Any]]:
    return [
        _step("100.0", "The user opens a.py.", ["x"], True),
        _step("130.4", "The user scrolls.", [], False),
        _step("160.0", "The user types.", ["y"], False),
    ]


def _event(category: str, label: str, i: int) -> BenchEvent:
    return BenchEvent(scene=f"{category}_1", category=category, index=i, label=label, events=["[now] e"])  # type: ignore[arg-type]


def _pool() -> list[BenchEvent]:
    return (
        [_event("code", "must", i) for i in range(6)]
        + [_event("code", "must_not", 10 + i) for i in range(2)]
        + [_event("writing", "must_not", i) for i in range(4)]
        + [_event("writing", "can", 10 + i) for i in range(5)]
    )


def test_to_label_status_true_is_must() -> None:
    assert to_label(True, []) == "must"


def test_to_label_false_without_candidates_is_can() -> None:
    assert to_label(False, ["  "]) == "can"
    assert to_label(False, ["task"]) == "must_not"


def test_format_events_marks_seconds_before_last() -> None:
    out = format_events([e["observation"] for e in _trace()])
    assert out == ["[60s ago] The user opens a.py.", "[30s ago] The user scrolls.", "[now] The user types."]


def test_format_events_empty() -> None:
    assert format_events([]) == []


def test_scene_events_expands_prefix_and_labels() -> None:
    events = scene_events("code_11", _trace())
    assert [e.label for e in events] == ["must", "can", "must_not"]
    assert events[1].events == ["[30s ago] The user opens a.py.", "[now] The user scrolls."]
    assert events[2].id == "code_11#2" and events[2].category == "code"


def test_scene_events_missing_agent_response_is_can() -> None:
    trace = [{"observation": {"time": "1", "event": "e"}, "task_status": False}]
    assert scene_events("writing_1", trace)[0].label == "can"


def test_to_thought_request_puts_events_as_external() -> None:
    request = to_thought_request(scene_events("code_11", _trace())[2], FIXED_CLOCK)
    assert request.mode == "reflection" and request.history == [] and request.open_loops == []
    assert request.external_events[-1] == "[now] The user types."


def test_stratified_sample_proportional_and_deterministic() -> None:
    picked = stratified_sample(_pool(), 6, seed=0)
    counts = {(e.category, e.label): 0 for e in picked}
    for e in picked:
        counts[(e.category, e.label)] += 1
    assert counts == {("code", "must"): 3, ("code", "must_not"): 1, ("writing", "must_not"): 2}
    assert [e.id for e in picked] == [e.id for e in stratified_sample(list(reversed(_pool())), 6, seed=0)]


def test_stratified_sample_limit_over_pool_takes_scored_only() -> None:
    picked = stratified_sample(_pool(), 100, seed=1)
    assert len(picked) == 12 and all(e.label != "can" for e in picked)
    assert stratified_sample(_pool(), 0, seed=1) == []


def test_vertex_score_combines_recall_and_quiet() -> None:
    assert vertex_score(0.8, 0.4) == 70.0


def test_vertex_score_missing_side_uses_other() -> None:
    assert vertex_score(None, 0.25) == 75.0
    assert vertex_score(None, None) == 0.0


def test_spoke_or_wrong_uses_would_speak() -> None:
    frame = ThoughtFrame(decision="act", confidence=0.9, utterance="hi")
    assert vertex.spoke_or_wrong("must", frame, False, 0.85) is True
    assert vertex.spoke_or_wrong("must", frame.model_copy(update={"confidence": 0.8}), False, 0.85) is False


def test_spoke_or_wrong_failure_counts_as_wrong() -> None:
    assert vertex.spoke_or_wrong("must", None, True, 0.85) is False
    assert vertex.spoke_or_wrong("must_not", None, True, 0.85) is True


class _Engine:
    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        if self.fail_on in request.external_events[-1]:
            raise TimeoutError
        return ThoughtFrame(decision="act", confidence=0.9, utterance="Need help?")


async def test_run_vertex_scores_with_mock_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vertex, "ensure_data", lambda: None)
    monkeypatch.setattr(vertex, "load_events", lambda: scene_events("code_11", _trace()))
    monkeypatch.setattr(vertex, "CACHE", tmp_path)
    monkeypatch.setattr(vertex, "build", lambda arm, model, decision: _Engine("opens"))
    result = await vertex.run_vertex("gpt-4o-mini", limit=5)
    assert result["n"] == 2 and result["errors"] == 1
    assert result["detail"]["recall"] == 0.0 and result["detail"]["false_alarm"] == 1.0
    assert result["score"] == 0.0


async def test_run_vertex_all_correct(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trace = _trace()[:1]
    monkeypatch.setattr(vertex, "ensure_data", lambda: None)
    monkeypatch.setattr(vertex, "load_events", lambda: scene_events("code_11", trace))
    monkeypatch.setattr(vertex, "CACHE", tmp_path)
    monkeypatch.setattr(vertex, "build", lambda arm, model, decision: _Engine("never"))
    result = await vertex.run_vertex("gpt-4o-mini")
    assert result["score"] == 100.0 and result["errors"] == 0 and result["detail"]["labels"] == {"must": 1}


def _row(label: str, confidence: float) -> dict[str, Any]:
    return {"label": label, "failed": False,
            "frame": ThoughtFrame(decision="act", confidence=confidence, utterance="Need help?")}


def test_calibrated_threshold_fits_each_models_confidence_scale() -> None:
    rows = [_row("must", 0.8), _row("must", 0.75), _row("must_not", 0.6)]
    assert vertex.calibrated_threshold(rows, 0.85) == 0.75


def test_calibrated_threshold_without_both_labels_falls_back() -> None:
    assert vertex.calibrated_threshold([_row("must", 0.8)], 0.85) == 0.85
    assert vertex.calibrated_threshold([], 0.85) == 0.85
