"""외부 알림: 슬랙과 디스코드 본문 포맷, webhook 전송, fan_out 격리, 종류 필터, proactive 이벤트 전달."""

from jarvis.core.notify import (
    discord_notifier,
    with_agents,
    fan_out,
    format_discord,
    format_slack,
    only_kinds,
    proactive_forwarder,
    proactive_payload,
    slack_notifier,
    spoken_payload,
)
from jarvis.agent_layer.agent_types import MessageUpdateEvent, ProactiveMessageEvent


def test_format_slack_reminder_and_proactive():
    assert format_slack({"type": "reminder", "name": "daily", "text": "날씨 맑음"}) == {"text": "*⏰ daily*\n날씨 맑음"}
    failed = format_slack({"type": "reminder", "name": "x", "text": "실패", "error": True})
    assert failed["text"].startswith("*⏰ x (실패)*")
    assert format_slack({"type": "proactive_message", "text": "배포 결과 공유 잊지 마세요"}) == {
        "text": "*💭 Jarvis*\n배포 결과 공유 잊지 마세요"
    }
    assert format_slack({"type": "weird"})["text"] == "*weird*\n{'type': 'weird'}"


def test_format_slack_truncates():
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


def test_format_discord_bolds_head_truncates_and_blocks_mentions():
    body = format_discord({"type": "reminder", "name": "daily", "text": "@everyone @here <@123> 메일 a@b.com"})
    assert body["content"] == "**⏰ daily**\n@\u200beveryone @\u200bhere <@\u200b123> 메일 a@b.com"
    assert body["allowed_mentions"] == {"parse": []}
    assert len(format_discord({"type": "proactive_message", "text": "x" * 5000})["content"]) == 2000


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


async def test_fan_out_isolates_failures_and_skips_none(capsys):
    got: list[dict] = []

    async def good(payload):
        got.append(payload)

    async def bad(payload):
        raise RuntimeError("down")

    notify = fan_out(bad, None, good)
    await notify({"type": "reminder"})
    assert got == [{"type": "reminder"}]
    assert "channel failed" in capsys.readouterr().out


async def test_only_kinds_filters_by_payload_type():
    got: list[str] = []

    async def sink(payload):
        got.append(payload["type"])

    notify = only_kinds(["reminder", "unknown"], sink)
    await notify({"type": "reminder"})
    await notify({"type": "proactive_message"})
    assert got == ["reminder"]


def test_proactive_payload_filters_fillers_and_other_events():
    ev = ProactiveMessageEvent(session_id="s", text="먼저 알림", kind="proactive", message_id="m1")
    assert proactive_payload(ev) == {
        "type": "proactive_message", "id": "m1", "session_id": "s", "kind": "proactive", "agent": "main",
        "text": "먼저 알림",
    }
    assert proactive_payload(ProactiveMessageEvent(session_id="s", text="잠깐만요", kind="filler")) is None
    assert proactive_payload(ProactiveMessageEvent(session_id="s", text="   ", kind="proactive")) is None
    assert proactive_payload(MessageUpdateEvent(text_delta="x")) is None
    # 시험 세션의 말은 밖으로 보내지 않는다
    assert proactive_payload(ProactiveMessageEvent(session_id="test-goal-nl-1", text="공고", kind="proactive")) is None


async def test_proactive_forwarder_swallows_channel_errors(capsys):
    async def boom(payload):
        raise RuntimeError("no network")

    listener = proactive_forwarder(boom)
    await listener(ProactiveMessageEvent(session_id="s", text="hi", kind="answer"))
    assert "forward failed" in capsys.readouterr().out


async def test_discord_posts_as_the_agent_named_in_the_payload():
    sent: list[dict] = []

    async def sink(payload):
        sent.append(format_discord(payload))

    notify = with_agents({"main": ("J.A.R.V.I.S.", "https://x/main.png"), "karen": ("K.A.R.E.N.", "")}, sink)
    await notify({"type": "proactive_message", "agent": "karen", "text": "공고 마감 임박"})
    await notify({"type": "reminder", "name": "daily", "text": "t"})  # agent 가 없으면 main
    await notify({"type": "reminder", "agent": "ghost", "name": "n", "text": "t"})  # 모르는 에이전트는 webhook 기본

    assert sent[0]["username"] == "K.A.R.E.N." and "avatar_url" not in sent[0]
    assert sent[0]["content"].startswith("**💭 K.A.R.E.N.**")
    assert (sent[1]["username"], sent[1]["avatar_url"]) == ("J.A.R.V.I.S.", "https://x/main.png")
    assert "username" not in sent[2]


def test_spoken_payload_skips_what_the_server_already_sent():
    assert spoken_payload("오늘 일정은 두 개예요", "karen", "reply") == {
        "type": "spoken", "agent": "karen", "source": "reply", "text": "오늘 일정은 두 개예요",
    }
    assert spoken_payload("At your service, sir.", "main", "phrase")["source"] == "phrase"
    # 🔔 과 ⏰ 은 서버가 이미 보냈다. 화면이 읽었다고 또 보내면 디스코드에 두 번 뜬다
    assert spoken_payload("회의 10분 전", "main", "reminder") is None
    assert spoken_payload("배포 결과 공유할까요?", "main", "proactive") is None
    assert spoken_payload("분석 끝났어요", "main", "answer") is None  # 뒤로 넘긴 작업의 답도 서버가 보냈다
    assert spoken_payload("   ", "main", "reply") is None


async def test_spoken_is_a_default_kind_and_reads_as_the_agent():
    sent: list[dict] = []

    async def sink(payload):
        sent.append(format_discord(payload))

    from jarvis.jarvis_config import NotifyConfig

    notify = only_kinds(NotifyConfig().kinds, with_agents({"karen": ("K.A.R.E.N.", "")}, sink))
    await notify(spoken_payload("공고 세 건 찾았어요", "karen", "reply"))
    assert sent[0]["content"] == "**🔊 K.A.R.E.N.**\n공고 세 건 찾았어요" and sent[0]["username"] == "K.A.R.E.N."


def test_tool_task_result_reads_like_a_task_result():
    tool = format_discord({"type": "reminder", "kind": "tool", "label": "새 LH 공고", "text": "새 LH 공고 1건"})
    assert tool["content"].startswith("**⏱ 새 LH 공고**")


def test_deferred_answer_reads_apart_from_a_proactive_message():
    answer = format_discord({"type": "proactive_message", "kind": "answer", "agent_name": "K.A.R.E.N.", "text": "끝"})
    nudge = format_discord({"type": "proactive_message", "kind": "proactive", "agent_name": "K.A.R.E.N.", "text": "?"})
    assert answer["content"].startswith("**💬 K.A.R.E.N.**") and nudge["content"].startswith("**💭 K.A.R.E.N.**")


def test_reminder_title_hides_names_the_schedule_command_made_up():
    from jarvis.core.scheduler.task import ScheduledTask, task_label

    once = ScheduledTask(name="once-ba15fed1", prompt="회의 자료 챙기기", kind="reminder")
    task = ScheduledTask(name="slash-1a2b3c4d", prompt="공고 새로 나온 것 정리해줘\n지역은 경기", kind="task")
    named = ScheduledTask(name="daily-news", prompt="뉴스 요약", kind="task")
    assert [task_label(t) for t in (once, task, named)] == ["알림", "공고 새로 나온 것 정리해줘", "daily-news"]
    head = format_discord({"type": "reminder", "name": "once-ba15fed1", "label": "알림", "text": "회의 자료 챙기기"})
    assert head["content"] == "**⏰ 알림**\n회의 자료 챙기기"


def test_task_results_use_the_same_icon_as_the_hud():
    task = format_discord({"type": "reminder", "kind": "task", "label": "공고 정리", "text": "세 건"})
    reminder = format_discord({"type": "reminder", "kind": "reminder", "label": "알림", "text": "회의"})
    assert task["content"].startswith("**⏱ 공고 정리**") and reminder["content"].startswith("**⏰ 알림**")


def test_recent_once_lets_the_same_key_through_once_per_window():
    from jarvis.core.notify.dedupe import RecentOnce

    now = [0.0]
    once = RecentOnce(10.0, lambda: now[0])
    # 같은 세션을 연 두 화면이 같은 답을 읽었다고 알려 온다
    assert once.first(("s1", "공고 세 건 찾았어요")) is True
    assert once.first(("s1", "공고 세 건 찾았어요")) is False
    assert once.first(("s2", "공고 세 건 찾았어요")) is True  # 다른 세션은 따로 센다
    now[0] = 10.0
    assert once.first(("s1", "공고 세 건 찾았어요")) is True


def test_split_speech_is_announced_once_with_the_whole_text():
    from jarvis.core.notify import spoken_notice_text

    assert spoken_notice_text("공고 두 건이에요.", None, "") == "공고 두 건이에요."
    whole = "공고 두 건이에요. 마감은 내일이에요."
    assert spoken_notice_text("공고 두 건이에요.", 0, whole) == whole
    assert spoken_notice_text("마감은 내일이에요.", 1, "") == ""
    assert spoken_notice_text("세 번째 문장.", 2, "") == ""
    # 첫 조각에 원문이 빠져 와도 그 조각은 알린다
    assert spoken_notice_text("공고 두 건이에요.", 0, "") == "공고 두 건이에요."
    # 빈 글이면 spoken_payload 가 알리지 않는다
    assert spoken_payload(spoken_notice_text("마감은 내일이에요.", 1, ""), "karen", "reply") is None
