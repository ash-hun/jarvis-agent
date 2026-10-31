"""notify: slack 이 알림 payload 를 슬랙 본문으로 바꾸고 webhook 실패를 로그로 남기는지 검증."""

import pytest

from jarvis.core.notify.slack import format_slack, slack_notifier


@pytest.mark.parametrize(
    ("payload", "text"),
    [
        ({"type": "reminder", "name": "daily", "text": "날씨 맑음"}, "*⏰ daily*\n날씨 맑음"),
        (
            {"type": "proactive_message", "text": "배포 결과 공유 잊지 마세요"},
            "*💭 Jarvis*\n배포 결과 공유 잊지 마세요",
        ),
        ({"type": "weird"}, "*weird*\n{'type': 'weird'}"),
    ],
)
def test_format_slack_formats_by_payload_type(payload, text):
    assert format_slack(payload) == {"text": text}


def test_format_slack_marks_failed_reminder():
    failed = format_slack({"type": "reminder", "name": "x", "text": "실패", "error": True})

    assert failed["text"].startswith("*⏰ x (실패)*")


def test_format_slack_truncates_long_text():
    assert len(format_slack({"type": "proactive_message", "text": "x" * 5000})["text"]) <= 2800


async def test_slack_notifier_posts_formatted_body_and_logs_failure(capsys):
    sent: list[tuple[str, dict]] = []

    async def fake_post(url, body):
        sent.append((url, body))
        return 500 if "fail" in body["text"] else 200

    notify = slack_notifier("https://hooks.example/abc", post=fake_post)

    await notify({"type": "reminder", "name": "n", "text": "ok"})
    await notify({"type": "reminder", "name": "n", "text": "fail"})

    assert sent[0] == ("https://hooks.example/abc", {"text": "*⏰ n*\nok"})
    assert "returned 500" in capsys.readouterr().out
