"""session 의 /export: 대화를 마크다운과 JSON 으로 바꾸고 파일로 쓰며, 빈 대화와 모르는 형식은 거절하는지 검증한다."""

import json
import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, Usage, UserMessage
from jarvis.core.slash.export_cmd import conversation_to_json, conversation_to_markdown, make_export_handler


def _assistant(text: str, model: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], model=model, usage=Usage(input=1, output=1))


def test_conversation_to_markdown_contains_roles_model_and_tool_result():
    msgs = [
        UserMessage(content="질문입니다"),
        _assistant("답변입니다", "claude-sonnet-4-5"),
        ToolResultMessage(tool_call_id="c1", tool_name="bash", content=[TextContent(text="결과")]),
    ]

    md = conversation_to_markdown(msgs, "sess1")

    assert "# Jarvis 대화 — sess1" in md
    for part in ("질문입니다", "답변입니다", "claude-sonnet-4-5", "bash", "결과"):
        assert part in md


def test_conversation_to_json_keeps_session_count_and_roles():
    msgs = [UserMessage(content="hi"), _assistant("yo", "m")]

    payload = json.loads(conversation_to_json(msgs, "sess1"))

    assert payload["session_id"] == "sess1"
    assert payload["message_count"] == 2
    assert payload["messages"][0]["role"] == "user"


@pytest.mark.parametrize(("args", "filename"), [("md", "default.md"), ("json", "default.json"), ("", "default.md")])
async def test_export_writes_file_in_requested_format(jsonl_repo, tmp_path, args, filename):
    await jsonl_repo.create(session_id="default")
    await jsonl_repo.append("default", UserMessage(content="안녕"))
    await jsonl_repo.append("default", _assistant("반가워요", "claude-sonnet-4-5"))

    out = await make_export_handler(jsonl_repo, export_dir=str(tmp_path))(args)

    assert "내보냈습니다" in out
    text = (tmp_path / filename).read_text(encoding="utf-8")
    assert "안녕" in text
    if filename.endswith(".json"):
        assert json.loads(text)["message_count"] == 2


async def test_export_refuses_empty_session_and_unknown_format(jsonl_repo, tmp_path):
    await jsonl_repo.create(session_id="default")
    exports = tmp_path / "exports"
    handler = make_export_handler(jsonl_repo, export_dir=str(exports))

    assert "내보낼 대화가 없습니다" in await handler("md")
    assert "사용법" in await handler("pdf")
    assert not exports.exists()
