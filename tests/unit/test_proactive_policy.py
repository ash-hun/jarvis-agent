"""proactive: 정책의 Dual-Channel 계획과 먼저 말하기 게이팅(임계치, 쿨다운, 응답 대기)을 검증한다."""

import pytest

from jarvis.core.proactive import DefaultProactivityPolicy, FeedbackLearner, ProactivityPolicy
from jarvis.agent_layer.thought.thought_types import ProactiveAction, ThoughtFrame


FILLER = "배포 로그 보고 올게요, 잠시만요"


ASK = ThoughtFrame(decision="ask", confidence=0.95, utterance="x")


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _policy(clock: _Clock, **kw) -> DefaultProactivityPolicy:
    return DefaultProactivityPolicy(confidence_threshold=0.5, clock=clock, **kw)


def test_default_policy_satisfies_protocol():
    assert isinstance(DefaultProactivityPolicy(), ProactivityPolicy)


@pytest.mark.parametrize(
    ("frame", "mode", "filler"),
    [
        (ThoughtFrame(needs_background=False), "immediate", ""),
        (ThoughtFrame(needs_background=True, filler=FILLER), "deferred", FILLER),
        (ThoughtFrame(needs_background=True, filler="   "), "deferred", None),
    ],
)
def test_plan_response_picks_mode_and_filler(frame, mode, filler):
    plan = DefaultProactivityPolicy().plan_response(frame)

    assert plan.mode == mode
    if filler is None:
        assert plan.filler.strip()
    else:
        assert plan.filler == filler


def test_plan_response_rotates_fallback_fillers():
    policy = DefaultProactivityPolicy()

    seen = {policy.plan_response(ThoughtFrame(needs_background=True)).filler for _ in range(3)}

    assert len(seen) >= 2


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (ThoughtFrame(decision="silent", confidence=0.9), "silent"),
        (ThoughtFrame(decision="ask", confidence=0.4), "confidence"),
    ],
)
def test_decide_proactive_suppresses_silent_or_low_confidence(frame, reason):
    decision = DefaultProactivityPolicy(confidence_threshold=0.6).decide_proactive(frame)

    assert decision.speak is False
    assert reason in decision.reason


def test_decide_proactive_speaks_and_splits_actions_by_risk():
    frame = ThoughtFrame(
        decision="act",
        confidence=0.8,
        utterance="배포 상태가 궁금한 듯",
        proactive_actions=[
            ProactiveAction(kind="tool", description="로그 읽기", risk="low"),
            ProactiveAction(kind="tool", description="재배포", risk="high"),
        ],
    )

    decision = DefaultProactivityPolicy(confidence_threshold=0.6).decide_proactive(frame)

    assert decision.speak is True
    assert decision.message == "배포 상태가 궁금한 듯"
    assert [a.risk for a in decision.autonomous_actions] == ["low"]
    assert [a.risk for a in decision.approval_actions] == ["high"]


def test_decide_proactive_follows_threshold_provider():
    learner = FeedbackLearner(base_threshold=0.6, step=0.05)
    policy = DefaultProactivityPolicy(threshold_provider=learner.threshold)
    frame = ThoughtFrame(decision="ask", confidence=0.58, utterance="x")
    before = policy.decide_proactive(frame, session_id="s1").speak

    learner.record(accepted=True)
    learner.record(accepted=True)

    assert before is False
    assert policy.decide_proactive(frame, session_id="s2").speak is True


def test_decide_proactive_cooldown_blocks_until_elapsed():
    clock = _Clock()
    policy = _policy(clock, cooldown_sec=300)
    first = policy.decide_proactive(ASK, session_id="s1")
    policy.note_user_activity("s1")

    clock.t += 100
    second = policy.decide_proactive(ASK, session_id="s1")
    clock.t += 250
    third = policy.decide_proactive(ASK, session_id="s1")

    assert first.speak is True
    assert second.speak is False and second.reason == "cooldown"
    assert third.speak is True


def test_decide_proactive_cooldown_is_per_session():
    policy = _policy(_Clock(), cooldown_sec=300)

    speaks = [policy.decide_proactive(ASK, session_id=s).speak for s in ("a", "b")]

    assert speaks == [True, True]


def test_decide_proactive_empty_utterance_is_silent_without_consuming_cooldown():
    policy = _policy(_Clock(), cooldown_sec=300)
    analysis_only = ThoughtFrame(decision="act", confidence=0.9, interpretation="사용자는 불안해 보인다", rationale="r")

    muted = policy.decide_proactive(analysis_only, session_id="s1")
    spoken = policy.decide_proactive(
        ThoughtFrame(decision="act", confidence=0.9, utterance="배포 결과 공유 잊지 마세요"), session_id="s1"
    )

    assert muted.speak is False and muted.reason == "empty utterance"
    assert spoken.speak is True and spoken.message == "배포 결과 공유 잊지 마세요"


def test_decide_proactive_awaiting_reply_blocks_even_after_cooldown():
    clock = _Clock()
    policy = _policy(clock, cooldown_sec=300)
    idle = policy.check_awaiting("s1")
    policy.decide_proactive(ASK, session_id="s1")

    clock.t += 3600
    blocked = policy.decide_proactive(ASK, session_id="s1")

    assert idle is None
    assert blocked.speak is False and blocked.reason == "awaiting reply"
    assert policy.decide_proactive(ASK, session_id="s2").speak is True


def test_note_user_activity_releases_gate_idempotently():
    policy = _policy(_Clock(), cooldown_sec=0)
    policy.decide_proactive(ASK, session_id="s1")

    policy.note_user_activity("s1")
    policy.note_user_activity("s1")
    policy.note_user_activity("never-spoke")

    assert policy.check_awaiting("s1") is None
    assert policy.decide_proactive(ASK, session_id="s1").speak is True


def test_check_awaiting_reports_ignored_once_per_utterance():
    clock = _Clock()
    policy = _policy(clock, cooldown_sec=0, ignore_after_sec=600)
    policy.decide_proactive(ASK, session_id="s1")
    seen = []
    for _ in range(3):
        clock.t += 300
        seen.append(policy.check_awaiting("s1").ignored)

    policy.note_user_activity("s1")
    policy.decide_proactive(ASK, session_id="s1")
    clock.t += 600

    assert seen == [False, True, False]
    assert policy.check_awaiting("s1").ignored is True


SPEAKING_FRAME = ThoughtFrame(decision="act", confidence=1.0, utterance="먼저 말할 거리")


def test_policy_default_is_immediate_and_silent():
    policy = ProactivityPolicy()
    policy.note_user_activity("s")

    decision = policy.decide_proactive(SPEAKING_FRAME, session_id="s")

    assert policy.plan_response(ThoughtFrame(needs_background=True, filler="잠시만")).mode == "immediate"
    assert policy.check_awaiting("s") is None
    assert decision.speak is False
    assert decision.reason == "proactivity disabled"
