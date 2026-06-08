"""Inner Thought 서브시스템 단위 테스트 — 실 API 없이 faux provider 사용."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from jarvis.agent_layer.memory.backends.in_memory_ltm import InMemoryLTMBackend
from jarvis.agent_layer.thought import (
    InnerThoughtEngine,
    LTMThoughtSink,
    STMThoughtSink,
    ThoughtEngine,
    ThoughtFrame,
    ThoughtLog,
    ThoughtPromptTemplate,
    ThoughtRequest,
)
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
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
    # 기본 템플릿 사용 — 고유 문구가 들어있고 플레이스홀더가 치환된다.
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
async def test_engine_extracts_json_from_noisy_output(faux_model_with_response):
    # 코드펜스/잡텍스트에 둘러싸여도 추출돼야 한다.
    noisy = "다음과 같이 생각합니다:\n```json\n" + _frame_json() + "\n```\n끝."
    model = faux_model_with_response(response=noisy)
    engine = InnerThoughtEngine(model=model, clock=_clock)

    frame = await engine.think(ThoughtRequest(user_input="질문"))
    assert frame is not None
    assert frame.observation.startswith("사용자가")


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
    backend = InMemoryLTMBackend()
    log = ThoughtLog([LTMThoughtSink(backend)])
    frame = ThoughtFrame(decision="ask", confidence=0.7, interpretation="x")

    await log.store(frame, session_id="s1")

    entries = await backend.get_recent(limit=10)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == THOUGHT_SOURCE
    assert entry.session_id == "s1"
    assert entry.metadata["decision"] == "ask"
    # content는 프레임 전체 JSON — 복원 가능해야 한다.
    restored = ThoughtFrame.model_validate_json(entry.content)
    assert restored.interpretation == "x"


@pytest.mark.asyncio
async def test_stm_sink_writes_tagged_message_without_polluting():
    from jarvis.agent_layer.memory.backends.in_memory_stm import InMemorySTMBackend

    stm = InMemorySTMBackend()
    log = ThoughtLog([STMThoughtSink(stm)])
    frame = ThoughtFrame(decision="silent", interpretation="속마음")

    await log.store(frame, session_id="s1")

    msgs = await stm.load("s1")
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    text = msgs[0].content[0].text
    assert THOUGHT_SOURCE in text and "속마음" in text


@pytest.mark.asyncio
async def test_thought_log_fans_out_to_multiple_sinks():
    from jarvis.agent_layer.memory.backends.in_memory_stm import InMemorySTMBackend

    ltm = InMemoryLTMBackend()
    stm = InMemorySTMBackend()
    log = ThoughtLog([LTMThoughtSink(ltm), STMThoughtSink(stm)])

    await log.store(ThoughtFrame(interpretation="y"), session_id="s1")

    assert len(await ltm.get_recent(limit=10)) == 1
    assert len(await stm.load("s1")) == 1


@pytest.mark.asyncio
async def test_thought_log_isolates_sink_failure():
    class BoomSink:
        async def store(self, frame, session_id=None):
            raise RuntimeError("sink down")

    ltm = InMemoryLTMBackend()
    log = ThoughtLog([BoomSink(), LTMThoughtSink(ltm)])

    # 한 싱크가 터져도 나머지는 저장되고 예외는 전파되지 않는다.
    await log.store(ThoughtFrame(interpretation="z"), session_id="s1")
    assert len(await ltm.get_recent(limit=10)) == 1


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
