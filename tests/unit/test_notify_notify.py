"""notify: 패키지 조합기 fan_out, only_kinds, with_agents 가 실패를 격리하고 종류를 거르며 에이전트로 보내는지 검증."""

from jarvis.core.notify import fan_out, format_discord, only_kinds, spoken_payload, with_agents
from jarvis.jarvis_config import NotifyConfig


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


async def test_with_agents_posts_as_the_agent_named_in_the_payload():
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


async def test_spoken_is_a_default_kind_and_reads_as_the_agent():
    sent: list[dict] = []

    async def sink(payload):
        sent.append(format_discord(payload))

    notify = only_kinds(NotifyConfig().kinds, with_agents({"karen": ("K.A.R.E.N.", "")}, sink))

    await notify(spoken_payload("공고 세 건 찾았어요", "karen", "reply"))

    assert sent[0]["content"] == "**🔊 K.A.R.E.N.**\n공고 세 건 찾았어요" and sent[0]["username"] == "K.A.R.E.N."
