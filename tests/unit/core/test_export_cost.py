"""/export · /cost 슬래시 커맨드 테스트."""
import json
import pytest

from jarvis.model_layer.model_types import (
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def _assistant(text: str, model: str, inp: int, out: int, cr: int = 0) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)],
        model=model,
        usage=Usage(input=inp, output=out, cache_read=cr),
    )


# ── /cost: 단가 테이블 ───────────────────────────────────────────────────────────

class TestCostRate:
    def test_known_models(self):
        from jarvis.core.slash.cost_cmd import cost_rate

        assert cost_rate("claude-opus-4") == (15.0, 75.0)
        assert cost_rate("claude-sonnet-4-5") == (3.0, 15.0)
        assert cost_rate("claude-haiku-4-5") == (0.8, 4.0)
        assert cost_rate("gemini-2.0") == (1.25, 5.0)

    def test_gpt4o_mini_before_gpt4o(self):
        """gpt-4o-mini가 gpt-4o보다 먼저 매칭돼야 한다."""
        from jarvis.core.slash.cost_cmd import cost_rate

        assert cost_rate("gpt-4o-mini") == (0.15, 0.6)
        assert cost_rate("gpt-4o") == (5.0, 15.0)

    def test_unknown_uses_default(self):
        from jarvis.core.slash.cost_cmd import cost_rate

        assert cost_rate("mystery-model") == (3.0, 15.0)
        assert cost_rate("") == (3.0, 15.0)

    def test_estimate_cost(self):
        from jarvis.core.slash.cost_cmd import estimate_cost

        # sonnet: 1M input * $3 + 1M output * $15 = $18
        assert estimate_cost("claude-sonnet-4-5", 1_000_000, 1_000_000) == pytest.approx(18.0)
        assert estimate_cost("claude-opus-4", 100_000, 0) == pytest.approx(1.5)


# ── /cost: 핸들러 ────────────────────────────────────────────────────────────────

class TestCostHandler:
    async def test_empty_session(self, jsonl_repo):
        from jarvis.core.slash.cost_cmd import make_cost_handler

        await jsonl_repo.create(session_id="default")
        handler = make_cost_handler(jsonl_repo)
        assert "집계할 사용량이 없습니다" in await handler("")

    async def test_aggregates_per_model(self, jsonl_repo):
        from jarvis.core.slash.cost_cmd import make_cost_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="hi"))
        await jsonl_repo.append("default", _assistant("a", "claude-sonnet-4-5", 1000, 500))
        await jsonl_repo.append("default", _assistant("b", "claude-sonnet-4-5", 2000, 800))

        out = await make_cost_handler(jsonl_repo)("")
        assert "claude-sonnet-4-5" in out
        assert "3,000" in out  # 합산 입력 1000+2000
        assert "$" in out
        assert "합계" in out

    async def test_multiple_models(self, jsonl_repo):
        from jarvis.core.slash.cost_cmd import make_cost_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", _assistant("a", "claude-opus-4", 1000, 100))
        await jsonl_repo.append("default", _assistant("b", "gpt-4o-mini", 5000, 200))

        out = await make_cost_handler(jsonl_repo)("")
        assert "claude-opus-4" in out
        assert "gpt-4o-mini" in out


# ── /export ──────────────────────────────────────────────────────────────────

class TestExportFormatting:
    def test_markdown_contains_roles(self):
        from jarvis.core.slash.export_cmd import conversation_to_markdown

        msgs = [
            UserMessage(content="질문입니다"),
            _assistant("답변입니다", "claude-sonnet-4-5", 10, 5),
            ToolResultMessage(tool_call_id="c1", tool_name="bash", content=[TextContent(text="결과")]),
        ]
        md = conversation_to_markdown(msgs, "sess1")
        assert "# Jarvis 대화 — sess1" in md
        assert "질문입니다" in md
        assert "답변입니다" in md
        assert "claude-sonnet-4-5" in md
        assert "bash" in md
        assert "결과" in md

    def test_json_structure(self):
        from jarvis.core.slash.export_cmd import conversation_to_json

        msgs = [UserMessage(content="hi"), _assistant("yo", "m", 1, 1)]
        payload = json.loads(conversation_to_json(msgs, "sess1"))
        assert payload["session_id"] == "sess1"
        assert payload["message_count"] == 2
        assert payload["messages"][0]["role"] == "user"


class TestExportHandler:
    async def test_empty_session(self, jsonl_repo, tmp_path):
        from jarvis.core.slash.export_cmd import make_export_handler

        await jsonl_repo.create(session_id="default")
        handler = make_export_handler(jsonl_repo, export_dir=str(tmp_path))
        assert "내보낼 대화가 없습니다" in await handler("md")

    async def test_invalid_format(self, jsonl_repo, tmp_path):
        from jarvis.core.slash.export_cmd import make_export_handler

        handler = make_export_handler(jsonl_repo, export_dir=str(tmp_path))
        assert "사용법" in await handler("pdf")

    async def test_writes_markdown_file(self, jsonl_repo, tmp_path):
        from jarvis.core.slash.export_cmd import make_export_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="안녕"))
        await jsonl_repo.append("default", _assistant("반가워요", "claude-sonnet-4-5", 5, 3))

        out = await make_export_handler(jsonl_repo, export_dir=str(tmp_path))("md")
        assert "내보냈습니다" in out
        f = tmp_path / "default.md"
        assert f.exists()
        assert "안녕" in f.read_text(encoding="utf-8")

    async def test_writes_json_file(self, jsonl_repo, tmp_path):
        from jarvis.core.slash.export_cmd import make_export_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="안녕"))

        out = await make_export_handler(jsonl_repo, export_dir=str(tmp_path))("json")
        assert "내보냈습니다" in out
        f = tmp_path / "default.json"
        assert f.exists()
        payload = json.loads(f.read_text(encoding="utf-8"))
        assert payload["message_count"] == 1

    async def test_default_format_is_markdown(self, jsonl_repo, tmp_path):
        from jarvis.core.slash.export_cmd import make_export_handler

        await jsonl_repo.create(session_id="default")
        await jsonl_repo.append("default", UserMessage(content="x"))

        await make_export_handler(jsonl_repo, export_dir=str(tmp_path))("")
        assert (tmp_path / "default.md").exists()
