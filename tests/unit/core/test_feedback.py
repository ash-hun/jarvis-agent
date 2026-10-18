"""피드백 학습(Tier 2 C3) — FeedbackLearner + 정책 동적 임계치."""
import pytest

from jarvis.core.proactive import DefaultProactivityPolicy, FeedbackLearner
from jarvis.agent_layer.thought.types import ThoughtFrame


def test_accept_lowers_threshold():
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    learner.record(accepted=True)
    assert learner.threshold() == pytest.approx(0.55)
    assert learner.stats()["accepts"] == 1


def test_dismiss_raises_threshold():
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    learner.record(accepted=False)
    assert learner.threshold() == pytest.approx(0.65)
    assert learner.stats()["dismisses"] == 1


def test_threshold_clamped_to_bounds():
    learner = FeedbackLearner(base_threshold=0.9, min_threshold=0.3, max_threshold=0.95, step=0.1)
    for _ in range(10):
        learner.record(accepted=False)
    assert learner.threshold() == pytest.approx(0.95)  # max 상한
    for _ in range(20):
        learner.record(accepted=True)
    assert learner.threshold() == pytest.approx(0.3)  # min 하한


def test_policy_uses_dynamic_threshold():
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    policy = DefaultProactivityPolicy(threshold_provider=learner.threshold)
    frame = ThoughtFrame(decision="ask", confidence=0.58, utterance="x")

    # 초기 임계 0.6 → 0.58은 미달 → silent.
    assert policy.decide_proactive(frame, session_id="s1").speak is False

    # 무시가 아닌 수락을 2회 → 임계 0.5로 하락 → 0.58 통과.
    learner.record(accepted=True)
    learner.record(accepted=True)
    assert policy.decide_proactive(frame, session_id="s2").speak is True


def test_policy_static_threshold_without_provider():
    policy = DefaultProactivityPolicy(confidence_threshold=0.6)
    frame = ThoughtFrame(decision="ask", confidence=0.7, utterance="x")
    assert policy.decide_proactive(frame).speak is True


def test_ignored_raises_threshold_by_half_step():
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    learner.record_ignored()
    assert learner.threshold() == pytest.approx(0.625)
    assert learner.stats()["ignores"] == 1


def test_ignored_clamped_to_max():
    learner = FeedbackLearner(base_threshold=0.95, step=0.05)
    learner.record_ignored()
    assert learner.threshold() == pytest.approx(0.95)
