"""session 의 /export: 대화를 마크다운과 JSON 으로 바꾸고 파일로 쓰며, 빈 대화와 모르는 형식은 거절하는지 검증한다."""

import json
import pytest

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolResultMessage, Usage, UserMessage
from jarvis.core.slash.export_cmd import conversation_to_json, conversation_to_markdown, make_export_handler
from jarvis.memory.scope import MemoryScope


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


@pytest.mark.parametrize(("args", "filename"), [("md", "work.md"), ("json", "work.json"), ("", "work.md")])
async def test_export_writes_calling_session_in_requested_format(jsonl_repo, tmp_path, args, filename):
    await jsonl_repo.create(session_id="default")
    await jsonl_repo.create(session_id="work")
    await jsonl_repo.append("work", UserMessage(content="안녕"))
    await jsonl_repo.append("work", _assistant("반가워요", "claude-sonnet-4-5"))

    scope = MemoryScope(user_id="local", session_id="work")

    out = await make_export_handler(jsonl_repo, export_dir=str(tmp_path))(args, scope)

    assert "내보냈습니다" in out
    text = (tmp_path / filename).read_text(encoding="utf-8")
    assert "안녕" in text
    if filename.endswith(".json"):
        assert json.loads(text)["message_count"] == 2


async def test_export_refuses_empty_session_and_unknown_format(jsonl_repo, tmp_path):
    await jsonl_repo.create(session_id="default")
    exports = tmp_path / "exports"
    handler = make_export_handler(jsonl_repo, export_dir=str(exports))
    scope = MemoryScope(user_id="local", session_id="default")

    assert "내보낼 대화가 없습니다" in await handler("md", scope)
    assert "사용법" in await handler("pdf", scope)
    assert not exports.exists()


async def test_export_filename_drops_path_characters_of_session_id(tmp_path):
    class _Repo:
        async def get_messages(self, _sid):
            return [UserMessage(content="hi")]

    exports = tmp_path / "exports"

    scope = MemoryScope(user_id="local", session_id="../../evil")

    await make_export_handler(_Repo(), export_dir=str(exports))("md", scope)

    assert [p.name for p in exports.iterdir()] == ["______evil.md"]
