"""thought 의 InnerThoughtEngine: 모드별 템플릿, 회상 주입, 관대한 프레임 파싱, 실패 시 None 을 검증한다."""

import json
import pytest
from datetime import datetime

from jarvis.agent_layer.thought import InnerThoughtEngine, ThoughtEngine, ThoughtPromptTemplate, ThoughtRequest
from jarvis.model_layer.model_types import ModelConfig, UserMessage
from jarvis.agent_layer.thought.engine import THOUGHT_SCHEMA
from jarvis.agent_layer.thought import engine as engine_mod
from tests.fixtures.thought_helpers import fake_llm

MODEL = ModelConfig(provider="faux", model="m")


def frame_json(**overrides) -> str:  # type: ignore[no-untyped-def]
    payload = {
        "observation": "사용자가 배포 상태를 물었다",
        "interpretation": "불안해서 빠른 확답을 원함",
        "recalled": ["어제 배포 실패 이력"],
        "options": ["로그 확인", "상태 요약"],
        "proactive_actions": [{"kind": "tool", "description": "배포 로그 읽기", "risk": "low"}],
        "decision": "ask",
        "confidence": 0.7,
        "rationale": "확신이 중간이라 묻는 편이 안전",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def clock() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (frame_json(), {"decision": "ask", "confidence": 0.7, "needs_background": False, "filler": ""}),
        (
            frame_json(needs_background=True, filler="잠깐만요, 확인하고 알려드릴게요"),
            {"needs_background": True, "filler": "잠깐만요, 확인하고 알려드릴게요"},
        ),
        (
            "다음과 같이 생각합니다:\n```json\n" + frame_json() + "\n```\n끝.",
            {"observation": "사용자가 배포 상태를 물었다"},
        ),
    ],
    ids=["valid", "dual_channel_fields", "noisy_output"],
)
async def test_think_parses_frame_fields(monkeypatch, raw, expected):
    fake_llm(monkeypatch, engine_mod, reply=raw)

    frame = await InnerThoughtEngine(model=MODEL, clock=clock).think(ThoughtRequest(user_input="배포 어떻게 됐어?"))

    assert frame is not None
    assert {k: getattr(frame, k) for k in expected} == expected
    assert frame.proactive_actions[0].risk == "low"


@pytest.mark.parametrize(
    ("mode", "used", "unused"), [("reflection", "[REFLECT]", "[REQUEST]"), ("request", "[REQUEST]", "[REFLECT]")]
)
async def test_think_picks_template_by_mode(monkeypatch, mode, used, unused):
    calls = fake_llm(monkeypatch, engine_mod, reply=frame_json())
    engine = InnerThoughtEngine(
        model=MODEL,
        template=ThoughtPromptTemplate("[REQUEST] {{user_input}}"),
        reflection_template=ThoughtPromptTemplate("[REFLECT] {{history}}"),
        clock=clock,
    )

    await engine.think(ThoughtRequest(user_input="씨앗", mode=mode))

    assert used in calls.prompts[0] and unused not in calls.prompts[0]


@pytest.mark.parametrize(
    ("raw", "skip_if_shorter_than", "mode", "user_input", "returns_frame"),
    [
        ("이건 JSON이 아니야", 0, "request", "질문", False),
        (frame_json(), 5, "request", "hi", False),
        (frame_json(), 100, "reflection", "x", True),
    ],
    ids=["broken_json", "short_request_skipped", "short_reflection_not_skipped"],
)
async def test_think_returns_none_on_broken_output_or_short_request(
    monkeypatch, raw, skip_if_shorter_than, mode, user_input, returns_frame
):
    fake_llm(monkeypatch, engine_mod, reply=raw)
    engine = InnerThoughtEngine(model=MODEL, skip_if_shorter_than=skip_if_shorter_than, clock=clock)

    frame = await engine.think(ThoughtRequest(user_input=user_input, mode=mode))

    assert (frame is not None) == returns_frame


async def test_think_injects_recalled_memories(monkeypatch):
    calls = fake_llm(monkeypatch, engine_mod, reply=frame_json())
    seen: dict = {}

    async def recall(query, context, limit):  # type: ignore[no-untyped-def]
        seen.update(query=query, limit=limit)
        return [UserMessage(content="과거 관련 기억")]

    engine = InnerThoughtEngine(
        model=MODEL, template=ThoughtPromptTemplate("{{recalled_memories}}"), recall=recall, recall_limit=3, clock=clock
    )

    await engine.think(ThoughtRequest(user_input="배포 상태", session_id="s1"))

    assert seen == {"query": "배포 상태", "limit": 3}
    assert calls.prompts[0] == "- 과거 관련 기억"


async def test_think_survives_recall_failure(monkeypatch):
    fake_llm(monkeypatch, engine_mod, reply=frame_json())

    async def boom(query, context, limit):  # type: ignore[no-untyped-def]
        raise RuntimeError("recall down")

    frame = await InnerThoughtEngine(model=MODEL, recall=boom, clock=clock).think(ThoughtRequest(user_input="질문"))

    assert frame is not None


def test_engine_satisfies_protocol(faux_model):
    assert isinstance(InnerThoughtEngine(model=faux_model), ThoughtEngine)


@pytest.mark.parametrize(
    ("raw", "decision", "options", "tool_names", "logs"),
    [
        (
            """```json
{"decision": "act", "confidence": 0.9, "interpretation": "상기",
 "proactive_actions": [
   {"kind": "calendar", "description": "캘린더 등록", "risk": "medium"},
   {"kind": "tool", "description": "로그 읽기", "tool_name": "read_file", "risk": "low"}
 ]}
```""",
            "act",
            None,
            ["read_file"],
            ["dropped invalid proactive_actions"],
        ),
        ('{"decision": "maybe", "confidence": "high"}', None, None, None, ["frame invalid", "decision"]),
        ('{"decision": "silent", "confidence": 0.2}', "silent", None, None, []),
        (
            '{"decision": "act", "confidence": 0.8, "options": [{"option": "바로 답한다"}, "되묻는다", 3]}',
            "act",
            ["바로 답한다", "되묻는다", "3"],
            None,
            [],
        ),
    ],
    ids=["drops_invalid_actions", "invalid_frame_logged", "valid_frame_quiet", "object_list_items_kept"],
)
async def test_think_parses_leniently_and_logs_why(monkeypatch, capsys, raw, decision, options, tool_names, logs):
    fake_llm(monkeypatch, engine_mod, reply=raw)

    frame = await InnerThoughtEngine(model=MODEL).think(ThoughtRequest(user_input="질문"))

    out = capsys.readouterr().out
    assert (frame.decision if frame else None) == decision
    if options is not None:
        assert frame is not None and frame.options == options
    if tool_names is not None:
        assert frame is not None and [a.tool_name for a in frame.proactive_actions] == tool_names
    assert all(fragment in out for fragment in logs) if logs else out == ""


def test_thought_schema_is_frame_schema_without_open_loops():
    assert set(THOUGHT_SCHEMA["properties"]) >= {"decision", "confidence", "utterance"}
    # 약속은 AGENDA 판단(openloop.judge)만 잡는다. 두 곳에서 잡으면 같은 약속이 다른 말로 쌓인다
    assert "open_loops" not in THOUGHT_SCHEMA["properties"]


@pytest.mark.parametrize(
    ("template", "check"),
    [
        ("[R] {{recent_proactive}}", lambda p: p == "[R] - 잘 되나요?"),
        ("[R] {{history}}", lambda p: "- 잘 되나요?" in p),
    ],
    ids=["with_slot", "old_template_appends"],
)
async def test_think_reflection_renders_recent_proactive(monkeypatch, template, check):
    calls = fake_llm(monkeypatch, engine_mod, reply=frame_json())
    engine = InnerThoughtEngine(model=MODEL, reflection_template=ThoughtPromptTemplate(template), clock=clock)

    await engine.think(ThoughtRequest(user_input="s", mode="reflection", recent_proactive=["잘 되나요?"]))

    assert check(calls.prompts[0])
