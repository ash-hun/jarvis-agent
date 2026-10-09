"""jarvis.memory 0단계: scope 규칙, 평가 스키마와 지표, 실행기, 베이스라인 특성."""

from datetime import datetime

import pytest

from jarvis.memory import MemoryKind, MemoryScope
from jarvis.memory.eval.metrics import judge
from jarvis.memory.eval.probe import count_llm_calls
from jarvis.memory.eval.runner import (
    DATASETS_DIR,
    STORE_SUITES,
    SUITES,
    format_report,
    load_suites,
    load_working_suites,
    run,
    run_working,
)
from jarvis.memory.eval.schema import EvalCase, Expect, ScopeSpec, SetupStep, load_cases
from jarvis.memory.eval.target import StoreTarget

# ── MemoryScope ───────────────────────────────────────────────────────────────


def test_child_scope_inherits_user_and_replaces_agent_and_session():
    parent = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
    child = parent.child(agent_id="researcher", session_id="agent_researcher__s1")
    assert child == MemoryScope("u1", "researcher", "agent_researcher__s1")


@pytest.mark.parametrize(
    ("reader", "item", "visibility", "visible"),
    [
        (MemoryScope("u1", "main"), MemoryScope("u1", "main", "s1"), "private", True),
        (MemoryScope("u1", "researcher"), MemoryScope("u1", "main"), "shared", True),
        (MemoryScope("u1", "researcher"), MemoryScope("u1", "main"), "private", False),
        (MemoryScope("u2", "main"), MemoryScope("u1", "main"), "shared", False),
        (MemoryScope("u1", "researcher"), MemoryScope("u1", "planner"), "private", False),
    ],
)
def test_read_inheritance_rules(reader, item, visibility, visible):
    assert reader.can_read(item, visibility) is visible


def test_working_set_requires_exact_match():
    a = MemoryScope("u1", "main", "s1")
    assert a.same_working_set(MemoryScope("u1", "main", "s1"))
    assert not a.same_working_set(MemoryScope("u1", "main", "s2"))


# ── 스키마와 지표 ────────────────────────────────────────────────────────────


def test_shipped_datasets_parse():
    for suite in STORE_SUITES:
        cases = load_cases(DATASETS_DIR / f"{suite}.jsonl")
        assert cases and all(c.suite == suite for c in cases)
    assert load_working_suites(["working"])
    assert set(SUITES) == {"isolation", "semantic", "episodic", "procedural", "working"}


def _case(**expect) -> EvalCase:
    return EvalCase(
        suite="t", case="c", setup=[], scope=ScopeSpec(user_id="u1"), probe="q", expect=Expect(**expect)
    )


def test_judge_contains_not_contains_and_empty():
    assert judge(_case(contains=["a"]), ["xa", "b"]).passed
    assert judge(_case(contains=["a"], top_k=1), ["b", "a"]).missing == ["a"]
    assert judge(_case(not_contains=["secret"]), ["the secret"]).leaked == ["secret"]
    assert judge(_case(empty=True), ["anything"]).broke_abstain
    assert judge(_case(empty=True), []).passed


# ── 실행기: 올바른 구현이면 통과한다 ─────────────────────────────────────────


class ScopedTarget:
    """읽기 상속 규칙을 지키는 참조 구현. 데이터셋이 만족 가능한지 증명한다."""

    def __init__(self) -> None:
        self._items: list[tuple[MemoryScope, str, str, datetime]] = []

    async def reset(self) -> None:
        self._items.clear()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        at = datetime.fromisoformat(step.at) if step.at else datetime.now()
        self._items.append((scope, step.visibility, step.remember, at))

    async def probe(self, query: str, scope: MemoryScope, top_k: int, kind: str = "recall") -> list[str]:
        tokens = query.split()
        hits = [
            (at, text)
            for s, vis, text, at in self._items
            if scope.can_read(s, vis) and any(t in text for t in tokens)
        ]
        hits.sort(reverse=True)
        # 지식 갱신: 같은 "주제:" 접두사는 최신 하나만
        seen: set[str] = set()
        out: list[str] = []
        for _, text in hits:
            topic = text.split(":")[0]
            if topic in seen:
                continue
            seen.add(topic)
            out.append(text)
        return out[:top_k]


@pytest.mark.memory_eval
async def test_isolation_suite_is_satisfiable_by_scope_aware_reference():
    """읽기 상속 규칙만 지키는 참조 구현으로 격리 스위트가 전부 통과한다(데이터셋 만족 가능성 증명)."""
    report = await run(load_suites(["isolation"]), ScopedTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["isolation"].leak_rate == 0.0


# ── 실제 저장소: 격리(1단계), 지식 갱신과 일화와 절차(3단계) ───────────────


@pytest.mark.memory_eval
async def test_store_isolates_users_and_agents():
    report = await run(load_suites(["isolation"]), StoreTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["isolation"].leak_rate == 0.0


@pytest.mark.memory_eval
async def test_store_prefers_latest_fact_and_abstains():
    report = await run(load_suites(["semantic"]), StoreTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["semantic"].leak_rate == 0.0
    assert report.suites["semantic"].abstain_rate == 1.0


@pytest.mark.memory_eval
async def test_store_episodic_and_procedural_suites_pass():
    report = await run(load_suites(["episodic", "procedural"]), StoreTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["episodic"].recall == 1.0
    assert report.suites["procedural"].recall == 1.0


# ── 비용 계측 ────────────────────────────────────────────────────────────────


async def test_count_llm_calls_wraps_provider(faux_model_with_response):
    from jarvis.model_layer.stream import stream_to_message
    from jarvis.model_layer.types import LLMContext, UserMessage

    model = faux_model_with_response("ok")
    ctx = LLMContext(messages=[UserMessage(content="hi")])
    with count_llm_calls("faux") as counter:
        await stream_to_message(model, ctx)
        await stream_to_message(model, ctx)
    assert counter.calls == 2
    await stream_to_message(model, ctx)
    assert counter.calls == 2  # 빠져나온 뒤엔 세지 않는다


def test_memory_kind_values():
    assert {k.value for k in MemoryKind} == {"episodic", "semantic", "procedural"}


# ── 작업 기억 스위트 ─────────────────────────────────────────────────────────


@pytest.mark.memory_eval
async def test_working_suite_passes():
    report = await run_working(load_working_suites(["working"]))
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["working"].total >= 5
