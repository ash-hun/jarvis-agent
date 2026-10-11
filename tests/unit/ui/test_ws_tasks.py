"""first_feedback: 같은 🔔 id 의 피드백은 연결당 한 번만 학습한다. id 가 없으면(옛 화면) 매번."""

from jarvis.ui.web.ws_tasks import first_feedback


def test_first_time_true_then_false():
    seen: set[str] = set()
    assert first_feedback(seen, "m1") is True
    assert first_feedback(seen, "m1") is False
    assert first_feedback(seen, "m2") is True
    assert seen == {"m1", "m2"}


def test_missing_or_non_string_id_always_true_and_not_recorded():
    seen: set[str] = set()
    for message_id in (None, "", 7, ["m1"]):
        assert first_feedback(seen, message_id) is True
        assert first_feedback(seen, message_id) is True
    assert seen == set()
