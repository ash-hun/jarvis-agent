"""notify: events 가 밖으로 보낼 말만 골라 payload 로 바꾸고 나눠 읽은 말은 한 번만 알리는지 검증."""

from jarvis.core.notify.events import proactive_forwarder, proactive_payload, spoken_notice_text, spoken_payload
from jarvis.agent_layer.agent_types import MessageUpdateEvent, ProactiveMessageEvent


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


def test_spoken_notice_text_announces_split_speech_once_with_the_whole_text():
    assert spoken_notice_text("공고 두 건이에요.", None, "") == "공고 두 건이에요."
    whole = "공고 두 건이에요. 마감은 내일이에요."
    assert spoken_notice_text("공고 두 건이에요.", 0, whole) == whole
    assert spoken_notice_text("마감은 내일이에요.", 1, "") == ""
    assert spoken_notice_text("세 번째 문장.", 2, "") == ""
    # 첫 조각에 원문이 빠져 와도 그 조각은 알린다
    assert spoken_notice_text("공고 두 건이에요.", 0, "") == "공고 두 건이에요."
    # 빈 글이면 spoken_payload 가 알리지 않는다
    assert spoken_payload(spoken_notice_text("마감은 내일이에요.", 1, ""), "karen", "reply") is None
