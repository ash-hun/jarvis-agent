"""jarvis.memory 0단계: scope 규칙, 평가 스키마와 지표, 실행기, 베이스라인 특성."""

import pytest
from datetime import datetime

from jarvis.memory.eval.runner import (
    DATASETS_DIR,
    REDESIGN_SUITES,
    STORE_SUITES,
    SUITES,
    format_report,
    load_retention_suites,
    load_suites,
    run,
    run_retention,
)
from jarvis.memory.eval.schema import EpisodeFilter, EvalCase, Expect, ScopeSpec, SetupStep, load_cases
from jarvis.memory.eval.probe import count_llm_calls
from jarvis.memory import MemoryKind, MemoryScope
from jarvis.memory.eval.target import EvalTarget
from jarvis.memory.eval.metrics import judge
from jarvis.memory.access import Readable

# ── MemoryScope ───────────────────────────────────────────────────────────────


def test_child_scope_inherits_user_and_replaces_agent_and_session():
    parent = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
    child = parent.child(agent_id="researcher", session_id="agent_researcher__s1")
    assert child == MemoryScope("u1", "researcher", "agent_researcher__s1")


def test_working_set_requires_exact_match():
    a = MemoryScope("u1", "main", "s1")
    assert a.same_working_set(MemoryScope("u1", "main", "s1"))
    assert not a.same_working_set(MemoryScope("u1", "main", "s2"))


# ── 스키마와 지표 ────────────────────────────────────────────────────────────


def test_shipped_datasets_parse():
    for suite in STORE_SUITES + REDESIGN_SUITES:
        cases = load_cases(DATASETS_DIR / f"{suite}.jsonl")
        assert cases and all(c.suite == suite for c in cases)
    assert load_retention_suites(["retention"])
    assert set(SUITES) == {
        "isolation", "semantic", "episodic", "procedural", "paraphrase", "access", "episode_filter",
        "consolidation", "retention", "faithfulness",
    }


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
    """사용자 경계와 기본 읽기 정책을 지키는 참조 구현. 데이터셋이 만족 가능한지 증명한다."""

    def __init__(self) -> None:
        self._items: list[tuple[MemoryScope, MemoryKind, str, datetime]] = []

    async def reset(self) -> None:
        self._items.clear()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        at = datetime.fromisoformat(step.at) if step.at else datetime.now()
        self._items.append((scope, step.kind, step.remember or "", at))

    async def probe(self, query: str, scope: MemoryScope, top_k: int, kind: str = "recall", *_: object) -> list[str]:
        tokens = query.split()
        hits = [
            (at, text)
            for s, kind, text, at in self._items
            if s.user_id == scope.user_id and Readable.own(scope.agent_id).allows(s.agent_id, kind)
            and any(t in text for t in tokens)
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
    """사용자 경계와 기본 읽기 정책만 지키는 참조 구현으로 격리 스위트가 전부 통과한다(데이터셋 만족 가능성 증명)."""
    report = await run(load_suites(["isolation"]), ScopedTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["isolation"].leak_rate == 0.0


class LayeredReference:
    """재설계 규칙(층별 허락, 일화 메타데이터, 성공 3회 정제)를 지키는 참조 구현. 풀 수 있는 데이터셋임을 보인다."""

    def __init__(self) -> None:
        self._items: list[tuple[MemoryScope, SetupStep]] = []

    async def reset(self) -> None:
        self._items.clear()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        self._items.append((scope, step))

    async def probe(
        self,
        query: str,
        scope: MemoryScope,
        top_k: int,
        kind: str = "recall",
        episode_filter: EpisodeFilter | None = None,
        policy: dict[str, dict[str, list[str]]] | None = None,
    ) -> list[str]:
        if kind == "candidates":
            successes: dict[str, int] = {}
            for s, step in self._items:
                if s == scope and step.task_type not in (None, "chat") and step.outcome == "success":
                    successes[step.task_type] = successes.get(step.task_type, 0) + 1
            return [t for t, n in successes.items() if n >= 3]
        hits = [
            step.remember or ""
            for s, step in self._items
            if self._readable(s, step, scope, policy or {}) and query in (step.remember or "")
            and (kind != "episodes" or step.kind is MemoryKind.EPISODIC and _matches(step, episode_filter))
        ]
        return hits[:top_k]

    @staticmethod
    def _readable(owner: MemoryScope, step: SetupStep, reader: MemoryScope, policy: dict) -> bool:
        layer = "pdm" if step.kind is MemoryKind.PROCEDURAL else "edm"
        allowed = policy.get(reader.agent_id, {}).get(layer, ["self"])
        agents = {reader.agent_id if a == "self" else a for a in allowed}
        return owner.user_id == reader.user_id and owner.agent_id in agents


def _matches(step: SetupStep, f: EpisodeFilter | None) -> bool:
    if f is None:
        return True
    at = step.at or ""
    return (
        (f.task_type is None or step.task_type == f.task_type)
        and (f.outcome is None or step.outcome == f.outcome)
        and (f.since is None or at >= f.since)
        and (f.until is None or at <= f.until)
    )


@pytest.mark.memory_eval
async def test_redesign_suites_are_satisfiable_by_layered_reference():
    report = await run(load_suites(list(REDESIGN_SUITES)), LayeredReference())
    assert report.all_passed, format_report(report, verbose=True)


@pytest.mark.memory_eval
async def test_redesign_suites_pass():
    report = await run(load_suites(list(REDESIGN_SUITES)), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["access"].leak_rate == 0.0


@pytest.mark.memory_eval
async def test_retention_keeps_every_distance_within_a_small_context():
    """STM 3턴 밖의 사실은 턴마다 쓴 EDM 에서 회상된다. 옛 50 메시지 창은 같은 사례에 117,786자를 넣었다."""
    report = await run_retention(load_retention_suites(["retention"]), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.injected_chars < 20_000


# ── 실제 저장소: 격리(1단계), 지식 갱신과 일화와 절차(3단계) ───────────────


@pytest.mark.memory_eval
async def test_store_isolates_users_and_agents():
    report = await run(load_suites(["isolation"]), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["isolation"].leak_rate == 0.0


@pytest.mark.memory_eval
async def test_store_prefers_latest_fact_and_abstains():
    report = await run(load_suites(["semantic"]), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["semantic"].leak_rate == 0.0
    assert report.suites["semantic"].abstain_rate == 1.0


@pytest.mark.memory_eval
async def test_store_episodic_and_procedural_suites_pass():
    report = await run(load_suites(["episodic", "procedural"]), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
    assert report.suites["episodic"].recall == 1.0
    assert report.suites["procedural"].recall == 1.0


# ── 비용 계측 ────────────────────────────────────────────────────────────────


async def test_count_llm_calls_wraps_provider(faux_model_with_response):
    from jarvis.model_layer.types import LLMContext, UserMessage
    from jarvis.model_layer.stream import stream_to_message

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


@pytest.mark.memory_eval
async def test_paraphrase_suite_passes_with_fake_embedder():
    report = await run(load_suites(["paraphrase"]), EvalTarget())
    assert report.all_passed, format_report(report, verbose=True)
