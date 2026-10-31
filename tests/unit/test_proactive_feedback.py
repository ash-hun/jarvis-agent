"""proactive: FeedbackLearner 가 수락, 거절, 무응답으로 임계치를 옮기고 상하한 안에 묶는지 검증한다."""

import pytest

from jarvis.core.proactive import FeedbackLearner


def _react(learner: FeedbackLearner, reaction: str) -> None:
    if reaction == "ignored":
        learner.record_ignored()
    else:
        learner.record(accepted=reaction == "accept")


@pytest.mark.parametrize(
    ("reaction", "threshold", "stat"),
    [("accept", 0.55, "accepts"), ("dismiss", 0.65, "dismisses"), ("ignored", 0.625, "ignores")],
)
def test_record_moves_threshold_by_reaction(reaction, threshold, stat):
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)

    _react(learner, reaction)

    assert learner.threshold() == pytest.approx(threshold)
    assert learner.stats()[stat] == 1


@pytest.mark.parametrize(
    ("base", "step", "reactions", "threshold"),
    [
        (0.9, 0.1, ["dismiss"] * 10, 0.95),
        (0.9, 0.1, ["dismiss"] * 10 + ["accept"] * 20, 0.3),
        (0.95, 0.05, ["ignored"], 0.95),
    ],
)
def test_threshold_clamped_to_bounds(base, step, reactions, threshold):
    learner = FeedbackLearner(base_threshold=base, min_threshold=0.3, max_threshold=0.95, step=step)

    for reaction in reactions:
        _react(learner, reaction)

    assert learner.threshold() == pytest.approx(threshold)
