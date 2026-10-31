"""notify: dedupe 가 짧은 시간 안 같은 키를 한 번만 통과시키는지 검증."""

from jarvis.core.notify.dedupe import RecentOnce


def test_recent_once_lets_the_same_key_through_once_per_window():
    now = [0.0]
    once = RecentOnce(10.0, lambda: now[0])

    # 같은 세션을 연 두 화면이 같은 답을 읽었다고 알려 온다
    assert once.first(("s1", "공고 세 건 찾았어요")) is True
    assert once.first(("s1", "공고 세 건 찾았어요")) is False
    assert once.first(("s2", "공고 세 건 찾았어요")) is True  # 다른 세션은 따로 센다
    now[0] = 10.0
    assert once.first(("s1", "공고 세 건 찾았어요")) is True
