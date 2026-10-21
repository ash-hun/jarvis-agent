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
)
from jarvis.agent_layer.types import MessageUpdateEvent, ProactiveMessageEvent


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
