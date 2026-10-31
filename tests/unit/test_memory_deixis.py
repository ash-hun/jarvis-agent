"""memory 기능의 상대 지칭: 지칭 감지, 직전 대화 추리기, 회상 질의 보강."""

import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from jarvis.memory.working.deixis import has_deixis, recent_exchange, retrieval_query

HISTORY = [
    UserMessage(content="배포 스크립트 고쳐줘", timestamp=0),
    AssistantMessage(content=[TextContent(text="롤백 방식으로 고쳤다")], timestamp=0),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("그거 다시 해줘", True),
        ("아까 말한 방법", True),
        ("do that again", True),
        ("그 방식 기억해", True),
        ("이 계획 괜찮아?", True),
        ("서울 날씨 알려줘", False),
        ("그래서 결론은", False),
    ],
)
def test_has_deixis_catches_korean_and_english_references(text, expected):
    assert bool(has_deixis(text)) is expected


def test_recent_exchange_skips_tool_results_and_stops_at_user():
    messages = [
        UserMessage(content="옛 질문", timestamp=0),
        AssistantMessage(content=[TextContent(text="옛 답")], timestamp=0),
        HISTORY[0],
        ToolResultMessage(tool_call_id="c", tool_name="bash", content=[TextContent(text="exit 0")]),
        HISTORY[1],
    ]

    assert recent_exchange(messages) == "배포 스크립트 고쳐줘\n롤백 방식으로 고쳤다"


@pytest.mark.parametrize(
    ("utterance", "prepends"),
    [("그거 스테이징에도 적용해", True), ("계속", True), ("서울 날씨 알려줘 주말까지", False)],
)
def test_retrieval_query_prepends_previous_exchange_only_when_needed(utterance, prepends):
    query = retrieval_query([*HISTORY, UserMessage(content=utterance, timestamp=0)])

    if prepends:
        assert query.startswith("배포 스크립트 고쳐줘")
    else:
        assert query == utterance
