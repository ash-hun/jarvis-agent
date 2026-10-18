"""[agent_layer] Inner Thought 서브시스템 단위 테스트(실 API 없이 faux provider 사용)."""

import json
import pytest
from datetime import datetime

from jarvis.agent_layer.thought import (
    InnerThoughtEngine,
    LTMThoughtSink,
    ThoughtEngine,
    ThoughtFrame,
    ThoughtLog,
    ThoughtPromptTemplate,
    ThoughtRequest,
    WorkingNotesSink,
)
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.memory.memory_service import MemoryService
from jarvis.model_layer.types import UserMessage


def _frame_json(**overrides) -> str:
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


def _clock() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0)


# ── 스키마 ────────────────────────────────────────────────────────────────────


def test_frame_defaults_to_silent():
    frame = ThoughtFrame()
    assert frame.decision == "silent"
    assert frame.confidence == 0.0
    assert frame.proactive_actions == []


def test_context_block_includes_interpretation_and_recall():
    frame = ThoughtFrame(interpretation="진짜 의도", recalled=["기억1", "기억2"])
    block = frame.context_block()
    assert "[내적 사고]" in block
    assert "진짜 의도" in block
    assert "기억1" in block and "기억2" in block


# ── 프롬프트 템플릿 ───────────────────────────────────────────────────────────


def test_template_renders_placeholders():
    tpl = ThoughtPromptTemplate("입력={{user_input}} 시각={{now}} 없음={{missing}}")
    out = tpl.render(user_input="안녕", now="T")
    assert "입력=안녕" in out
    assert "시각=T" in out
    # PLACEHOLDERS에 없는 키는 치환되지 않고 그대로 남는다.
    assert "{{missing}}" in out


def test_template_load_falls_back_when_missing(tmp_path):
    tpl = ThoughtPromptTemplate.load(str(tmp_path / "nonexistent.md"))
    # 기본 템플릿 사용: 고유 문구가 들어있고 플레이스홀더가 치환된다.
    out = tpl.render(user_input="ZZZ")
    assert "내적 사고" in out
    assert "ZZZ" in out


def test_template_load_reads_file(tmp_path):
    p = tmp_path / "inner_thought.md"
    p.write_text("커스텀 {{user_input}}", encoding="utf-8")
    tpl = ThoughtPromptTemplate.load(str(p))
    assert tpl.render(user_input="X") == "커스텀 X"


# ── 엔진: 정상 파싱 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_parses_valid_frame(faux_model_with_response):
    model = faux_model_with_response(response=_frame_json())
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="배포 어떻게 됐어?"))

    assert frame is not None
    assert frame.decision == "ask"
    assert frame.confidence == 0.7
    assert frame.proactive_actions[0].risk == "low"


@pytest.mark.asyncio
async def test_engine_parses_dual_channel_fields(faux_model_with_response):
    # needs_background / filler가 프레임으로 파싱돼야 한다(Tier 1 Dual-Channel 입력).
    model = faux_model_with_response(
        response=_frame_json(needs_background=True, filler="잠깐만요, 확인하고 알려드릴게요")
    )
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="배포 로그 분석해줘"))
    assert frame is not None
    assert frame.needs_background is True
    assert frame.filler == "잠깐만요, 확인하고 알려드릴게요"


@pytest.mark.asyncio
async def test_engine_dual_channel_defaults_when_absent(faux_model_with_response):
    # 모델이 새 필드를 안 주면 기본값(즉답 모드).
    model = faux_model_with_response(response=_frame_json())
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="안녕"))
    assert frame is not None
    assert frame.needs_background is False
    assert frame.filler == ""


@pytest.mark.asyncio
async def test_engine_extracts_json_from_noisy_output(faux_model_with_response):
    # 코드펜스/잡텍스트에 둘러싸여도 추출돼야 한다.
    noisy = "다음과 같이 생각합니다:\n```json\n" + _frame_json() + "\n```\n끝."
    model = faux_model_with_response(response=noisy)
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="질문"))
    assert frame is not None
    assert frame.observation.startswith("사용자가")


# ── 엔진: reflection 전용 템플릿 (E3) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_uses_reflection_template_in_reflection_mode(faux_model_with_response):
    captured: dict = {}

    class SpyEngine(InnerThoughtEngine):
        async def _call_model(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return _frame_json()

    req_tpl = ThoughtPromptTemplate("[REQUEST] {{user_input}}")
    refl_tpl = ThoughtPromptTemplate("[REFLECT] {{history}}")
    model = faux_model_with_response(response=_frame_json())
    engine = SpyEngine(
        model=model, template=req_tpl, reflection_template=refl_tpl, clock=_clock
    )

    await engine.think(ThoughtRequest(user_input="씨앗", mode="reflection"))
    assert "[REFLECT]" in captured["prompt"]
    assert "[REQUEST]" not in captured["prompt"]


@pytest.mark.asyncio
async def test_engine_uses_request_template_by_default(faux_model_with_response):
    captured: dict = {}

    class SpyEngine(InnerThoughtEngine):
        async def _call_model(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return _frame_json()

    engine = SpyEngine(
        model=faux_model_with_response(response=_frame_json()),
        template=ThoughtPromptTemplate("[REQUEST] {{user_input}}"),
        reflection_template=ThoughtPromptTemplate("[REFLECT]"),
        clock=_clock,
    )
    await engine.think(ThoughtRequest(user_input="질문"))  # mode 기본 request
    assert "[REQUEST]" in captured["prompt"]


@pytest.mark.asyncio
async def test_reflection_mode_not_skipped_by_short_input(faux_model_with_response):
    # skip_if_shorter_than이 커도 reflection은 생략되지 않는다.
    model = faux_model_with_response(response=_frame_json())
    engine = InnerThoughtEngine(model=model, skip_if_shorter_than=100, clock=_clock)
    frame = await engine.think(ThoughtRequest(user_input="x", mode="reflection"))
    assert frame is not None


def test_template_load_accepts_custom_default(tmp_path):
    from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE

    tpl = ThoughtPromptTemplate.load(
        str(tmp_path / "missing.md"), default=DEFAULT_REFLECTION_TEMPLATE
    )
    out = tpl.render()
    assert "자율 성찰" in out  # reflection 기본 템플릿으로 폴백


# ── 엔진: graceful fallback ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_returns_none_on_broken_json(faux_model_with_response):
    model = faux_model_with_response(response="이건 JSON이 아니야")
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="질문"))
    assert frame is None  # 메인 턴은 계속 진행되어야 함


@pytest.mark.asyncio
async def test_engine_skips_short_input(faux_model_with_response):
    model = faux_model_with_response(response=_frame_json())
    engine = InnerThoughtEngine(model=model, skip_if_shorter_than=5, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="hi"))
    assert frame is None  # 사고 생략(지연/비용 완화)


# ── 엔진: 회상 콜백 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_invokes_recall_and_injects(faux_model_with_response):
    captured: dict = {}

    async def fake_recall(query, context, limit):
        captured["query"] = query
        captured["limit"] = limit
        return [UserMessage(content="과거 관련 기억")]

    rendered: dict = {}

    class SpyEngine(InnerThoughtEngine):
        def _render(self, request, recalled):
            rendered["recalled"] = recalled
            return super()._render(request, recalled)

    model = faux_model_with_response(response=_frame_json())
    engine = SpyEngine(model=model, recall=fake_recall, recall_limit=3, clock=_clock)

    await engine.think(ThoughtRequest(user_input="배포 상태", session_id="s1"))

    assert captured["query"] == "배포 상태"
    assert captured["limit"] == 3
    assert rendered["recalled"] == ["과거 관련 기억"]


@pytest.mark.asyncio
async def test_engine_recall_failure_is_swallowed(faux_model_with_response):
    async def boom(query, context, limit):
        raise RuntimeError("recall down")

    model = faux_model_with_response(response=_frame_json())
    engine = InnerThoughtEngine(model=model, recall=boom, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="질문"))
    assert frame is not None  # 회상 실패해도 사고는 계속


# ── Protocol 준수 ─────────────────────────────────────────────────────────────


def test_engine_satisfies_protocol(faux_model):
    engine = InnerThoughtEngine(model=faux_model)
    assert isinstance(engine, ThoughtEngine)


# ── ThoughtLog 싱크 (A2) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ltm_sink_persists_full_frame():
    backend = MemoryService(InMemoryItemStore())
    log = ThoughtLog([LTMThoughtSink(backend)])
    frame = ThoughtFrame(decision="ask", confidence=0.7, interpretation="x")

    await log.store(frame, session_id="s1")

    entries = await backend.recent(limit=10)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == THOUGHT_SOURCE
    assert entry.session_id == "s1"
    assert entry.metadata["decision"] == "ask"
    # content는 프레임 전체 JSON: 복원 가능해야 한다.
    restored = ThoughtFrame.model_validate_json(entry.content)
    assert restored.interpretation == "x"


@pytest.mark.asyncio
async def test_notes_sink_writes_to_working_memory_not_to_context():
    from jarvis.memory import MemoryScope

    memory = MemoryService(InMemoryItemStore())
    log = ThoughtLog([WorkingNotesSink(memory)])
    frame = ThoughtFrame(decision="silent", interpretation="속마음")

    await log.store(frame, session_id="s1")

    notes = (await memory.working_state(MemoryScope(user_id="local", session_id="s1"))).notes
    assert len(notes) == 1 and THOUGHT_SOURCE in notes[0] and "속마음" in notes[0]
    assert await memory.recent() == []  # 장기 기억에는 쓰지 않는다


@pytest.mark.asyncio
async def test_thought_log_fans_out_to_multiple_sinks():
    from jarvis.memory import MemoryScope

    ltm = MemoryService(InMemoryItemStore())
    log = ThoughtLog([LTMThoughtSink(ltm), WorkingNotesSink(ltm)])

    await log.store(ThoughtFrame(interpretation="y"), session_id="s1")

    assert len(await ltm.recent(limit=10)) == 1
    assert len((await ltm.working_state(MemoryScope(user_id="local", session_id="s1"))).notes) == 1


@pytest.mark.asyncio
async def test_thought_log_isolates_sink_failure():
    class BoomSink:
        async def store(self, frame, session_id=None):
            raise RuntimeError("sink down")

    ltm = MemoryService(InMemoryItemStore())
    log = ThoughtLog([BoomSink(), LTMThoughtSink(ltm)])

    # 한 싱크가 터져도 나머지는 저장되고 예외는 전파되지 않는다.
    await log.store(ThoughtFrame(interpretation="z"), session_id="s1")
    assert len(await ltm.recent(limit=10)) == 1


# ── Composer (A3) ─────────────────────────────────────────────────────────────


def test_default_composer_uses_context_block():
    from jarvis.agent_layer.thought import DefaultThoughtComposer

    frame = ThoughtFrame(interpretation="의도", recalled=["기억"])
    out = DefaultThoughtComposer().compose(frame)
    assert "[내적 사고]" in out and "의도" in out and "기억" in out


def test_interpretation_only_composer_is_lean():
    from jarvis.agent_layer.thought import InterpretationOnlyComposer

    frame = ThoughtFrame(interpretation="의도", recalled=["기억"], options=["A", "B"])
    out = InterpretationOnlyComposer().compose(frame)
    assert out == "[내적 사고] 의도"
    assert "기억" not in out  # 회상/옵션 생략

    # interpretation이 없으면 빈 문자열(주입 안 함).
    assert InterpretationOnlyComposer().compose(ThoughtFrame()) == ""


# ── 관대한 파싱 ───────────────────────────────────────────────────────────────


def _engine():
    from jarvis.agent_layer.thought.engine import InnerThoughtEngine
    from jarvis.model_layer.types import ModelConfig

    return InnerThoughtEngine(model=ModelConfig(provider="faux", model="m"))


def test_parse_drops_invalid_actions_but_keeps_frame(capsys):
    raw = """```json
{"decision": "act", "confidence": 0.9, "interpretation": "상기",
 "proactive_actions": [
   {"kind": "calendar", "description": "캘린더 등록", "risk": "medium"},
   {"kind": "tool", "description": "로그 읽기", "tool_name": "read_file", "risk": "low"}
 ]}
```"""
    frame = _engine()._parse(raw)
    assert frame is not None and frame.decision == "act"
    assert [a.tool_name for a in frame.proactive_actions] == ["read_file"]
    assert "dropped invalid proactive_actions" in capsys.readouterr().out


def test_parse_logs_reason_when_frame_itself_invalid(capsys):
    frame = _engine()._parse('{"decision": "maybe", "confidence": "high"}')
    assert frame is None
    out = capsys.readouterr().out
    assert "frame invalid" in out and "decision" in out


def test_parse_valid_frame_is_silent(capsys):
    frame = _engine()._parse('{"decision": "silent", "confidence": 0.2}')
    assert frame is not None and frame.decision == "silent"
    assert capsys.readouterr().out == ""


def test_parse_keeps_frame_when_list_items_are_objects(capsys):
    """작은 모델은 options 에 객체를 넣는다. 글자만 건지고 프레임은 산다."""
    raw = ('{"decision": "act", "confidence": 0.8, "options": [{"option": "바로 답한다"}, "되묻는다", 3],'
           ' "open_loops": [{"description": "배포 로그 확인", "due": "오늘"}]}')
    frame = _engine()._parse(raw)
    assert frame is not None and frame.options == ["바로 답한다", "되묻는다", "3"]
    assert frame.open_loops == ["배포 로그 확인 오늘"]
    assert capsys.readouterr().out == ""


def test_thought_schema_is_frame_schema():
    from jarvis.agent_layer.thought.engine import THOUGHT_SCHEMA

    assert set(THOUGHT_SCHEMA["properties"]) >= {"decision", "confidence", "utterance", "open_loops"}


@pytest.mark.asyncio
async def test_reflection_renders_recent_proactive(faux_model_with_response):
    captured: list[str] = []

    class SpyEngine(InnerThoughtEngine):
        async def _call_model(self, prompt: str) -> str:
            captured.append(prompt)
            return _frame_json()

    model = faux_model_with_response(response=_frame_json())
    with_slot = SpyEngine(
        model=model, reflection_template=ThoughtPromptTemplate("[R] {{recent_proactive}}"), clock=_clock
    )
    await with_slot.think(ThoughtRequest(user_input="s", mode="reflection", recent_proactive=["잘 되나요?"]))
    assert captured[-1] == "[R] - 잘 되나요?"

    # 사용자가 편집한 옛 템플릿엔 자리가 없다. 끝에 덧붙여 유실을 막는다
    no_slot = SpyEngine(model=model, reflection_template=ThoughtPromptTemplate("[R] {{history}}"), clock=_clock)
    await no_slot.think(ThoughtRequest(user_input="s", mode="reflection", recent_proactive=["잘 되나요?"]))
    assert "- 잘 되나요?" in captured[-1]
