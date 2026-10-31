"""procedures 기능의 증류: 초안 JSON 파싱, 이름 slug, 프롬프트 렌더, LLM 증류기의 성공과 실패."""

import pytest

from jarvis.core.procedures import ProcedureDraft, TaskSpan, ToolStep, find_spans, llm_distiller, parse_draft
from jarvis.model_layer.model_types import AssistantMessage, ModelConfig, TextContent
from tests.fixtures.procedures_helpers import PLAN_JSON, success_history
from jarvis.core.procedures.distill import render_prompt, slugify

MODEL = ModelConfig(provider="faux", model="faux-model")
SPAN = TaskSpan(
    start=0,
    request="테스트 돌리고 요약해줘",
    steps=(ToolStep(name="bash", args={"command": "pytest"}),),
    outcome="3개 통과",
)


def test_parse_draft_extracts_json_and_slugifies_name():
    raw = (
        'Sure:\n```json\n'
        '{"name": "Run Tests & Summarize!", "description": "테스트 실행", "parameters": "", "steps": ["1", " 2 "]}'
        "\n```"
    )

    draft = parse_draft(raw)

    assert draft == ProcedureDraft(name="run-tests-summarize", description="테스트 실행", steps=("1", "2"))


@pytest.mark.parametrize("raw", ["", "not json", '{"name": "x"}', '{"description": "d", "steps": []}', "[1,2]"])
def test_parse_draft_rejects_incomplete(raw):
    assert parse_draft(raw) is None


def test_parse_draft_keeps_plan_only_when_every_step_is_complete():
    draft = parse_draft(PLAN_JSON)
    half = parse_draft(PLAN_JSON.replace('"args": {"path": "{{log}}"}', '"args": "x"'))

    assert draft is not None and draft.inputs == ("test_dir", "log") and len(draft.plan) == 3
    assert half is not None and half.plan == ()


@pytest.mark.parametrize(("name", "expected"), [("한국어 이름", "procedure"), ("a" * 80, "a" * 40)])
def test_slugify_falls_back_or_truncates(name, expected):
    assert slugify(name) == expected


def test_render_prompt_truncates_long_args():
    found = find_spans(success_history())[0]
    long_step = ToolStep("write_file", {"content": "x" * 1000})
    span = TaskSpan(start=0, request=found.request, outcome=found.outcome, steps=(long_step,))

    prompt = render_prompt(span)

    assert "x" * 1000 not in prompt and "…" in prompt


async def test_llm_distiller_parses_reply(monkeypatch):
    prompts: list[str] = []

    async def fake_stream(model, ctx, options):
        prompts.append(ctx.messages[0].content)
        reply = '{"name": "Run Tests", "description": "테스트 요약", "steps": ["bash 로 실행"]}'
        return AssistantMessage(content=[TextContent(text=reply)])

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    draft = await llm_distiller(MODEL)(SPAN)

    assert draft is not None
    assert (draft.name, draft.description, draft.steps) == ("run-tests", "테스트 요약", ("bash 로 실행",))
    assert "테스트 돌리고 요약해줘" in prompts[0]


async def test_llm_distiller_returns_none_on_model_error(monkeypatch):
    async def fake_stream(model, ctx, options):
        return AssistantMessage(content=[TextContent(text="{}")], error_message="rate limited")

    monkeypatch.setattr("jarvis.model_layer.stream.stream_to_message", fake_stream)

    assert await llm_distiller(MODEL)(SPAN) is None
