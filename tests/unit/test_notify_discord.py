"""notify: discord 가 payload 를 디스코드 본문으로 바꾸고(머리, 길이, 멘션 막기) webhook 을 한 번만 보내는지 검증."""

import pytest

from jarvis.core.notify.discord import discord_notifier, format_discord
from jarvis.core.scheduler.task import ScheduledTask, task_label


def test_format_discord_bolds_head_truncates_and_blocks_mentions():
    body = format_discord({"type": "reminder", "name": "daily", "text": "@everyone @here <@123> 메일 a@b.com"})

    assert body["content"] == "**⏰ daily**\n@​everyone @​here <@​123> 메일 a@b.com"
    assert body["allowed_mentions"] == {"parse": []}
    assert len(format_discord({"type": "proactive_message", "text": "x" * 5000})["content"]) == 2000


@pytest.mark.parametrize(
    ("payload", "head"),
    [
        ({"type": "reminder", "kind": "tool", "label": "새 LH 공고", "text": "새 LH 공고 1건"}, "**⏱ 새 LH 공고**"),
        # 작업 결과는 HUD 와 같은 아이콘을 쓴다
        ({"type": "reminder", "kind": "task", "label": "공고 정리", "text": "세 건"}, "**⏱ 공고 정리**"),
        ({"type": "reminder", "kind": "reminder", "label": "알림", "text": "회의"}, "**⏰ 알림**"),
        # 뒤로 넘긴 작업의 답은 먼저 건넨 말과 다르게 보인다
        (
            {"type": "proactive_message", "kind": "answer", "agent_name": "K.A.R.E.N.", "text": "끝"},
            "**💬 K.A.R.E.N.**",
        ),
        (
            {"type": "proactive_message", "kind": "proactive", "agent_name": "K.A.R.E.N.", "text": "?"},
            "**💭 K.A.R.E.N.**",
        ),
    ],
    ids=["tool_task", "task", "reminder", "deferred_answer", "proactive"],
)
def test_format_discord_heads_by_kind(payload, head):
    assert format_discord(payload)["content"].startswith(head)


def test_reminder_title_hides_names_the_schedule_command_made_up():
    once = ScheduledTask(name="once-ba15fed1", prompt="회의 자료 챙기기", kind="reminder")
    task = ScheduledTask(name="slash-1a2b3c4d", prompt="공고 새로 나온 것 정리해줘\n지역은 경기", kind="task")
    named = ScheduledTask(name="daily-news", prompt="뉴스 요약", kind="task")

    head = format_discord({"type": "reminder", "name": "once-ba15fed1", "label": "알림", "text": "회의 자료 챙기기"})

    assert [task_label(t) for t in (once, task, named)] == ["알림", "공고 새로 나온 것 정리해줘", "daily-news"]
    assert head["content"] == "**⏰ 알림**\n회의 자료 챙기기"


async def test_discord_notifier_posts_once_and_logs_failure(capsys):
    sent: list[tuple[str, dict]] = []

    async def fake_post(url, body):
        sent.append((url, body))
        return 429 if "fail" in body["content"] else 204

    notify = discord_notifier("https://discord.com/api/webhooks/1/t", post=fake_post)

    await notify({"type": "proactive_message", "text": "ok"})
    await notify({"type": "proactive_message", "text": "fail"})

    assert [b["content"] for _, b in sent] == ["**💭 Jarvis**\nok", "**💭 Jarvis**\nfail"]  # 429 도 다시 보내지 않는다
    assert "discord webhook returned 429" in capsys.readouterr().out
