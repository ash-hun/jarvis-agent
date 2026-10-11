"""절차 학습: 구간 탐지, 초안 파싱, 저장소 upsert, 학습의 멱등성, 도구와 스킬 노출, /procedures."""

import pytest

from jarvis.core.procedures import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    TOOL_PREFIX,
    Procedure,
    ProcedureDraft,
    ProcedureLearner,
    ProcedureStore,
    ProcedureTool,
    find_spans,
    parse_draft,
    register_approved,
)
from jarvis.core.procedures.distill import render_prompt, slugify
from jarvis.core.procedures.learner import unique_name
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.tools.registry import ToolRegistry
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolCall, ToolResultMessage, UserMessage

# ── 픽스처: 도구 3번 쓰고 성공으로 끝난 대화 ──────────────────────────────────


def _tool_turn(call_id: str, name: str, args: dict, is_error: bool = False) -> list:
    return [
        AssistantMessage(content=[ToolCall(id=call_id, name=name, arguments=args)], stop_reason="tool_use"),
        ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[TextContent(text="ok")], is_error=is_error),
    ]


def _success_history(request: str = "테스트 돌리고 요약해줘") -> list:
    return [
        UserMessage(content=request),
        *_tool_turn("c1", "glob", {"pattern": "tests/**/*.py"}),
        *_tool_turn("c2", "bash", {"command": "uv run pytest -q"}),
        *_tool_turn("c3", "read_file", {"path": "pytest.log"}),
        AssistantMessage(content=[TextContent(text="전부 통과했습니다.")], stop_reason="stop"),
    ]


def test_find_spans_detects_successful_multi_tool_task():
    spans = find_spans(_success_history())
    assert len(spans) == 1
    span = spans[0]
    assert span.start == 0
    assert span.request == "테스트 돌리고 요약해줘"
    assert [s.name for s in span.steps] == ["glob", "bash", "read_file"]
    assert span.tool_names == ("glob", "bash", "read_file")
    assert span.outcome == "전부 통과했습니다."


def test_find_spans_respects_min_tool_calls():
    assert find_spans(_success_history(), min_tool_calls=4) == []


def test_find_spans_drops_span_with_tool_error_or_no_outcome():
    with_error = _success_history()
    with_error[4] = ToolResultMessage(
        tool_call_id="c2", tool_name="bash", content=[TextContent(text="boom")], is_error=True
    )
    assert find_spans(with_error) == []

    no_outcome = _success_history()[:-1]
    assert find_spans(no_outcome) == []


def test_find_spans_splits_on_user_messages_and_indexes_by_start():
    history = [UserMessage(content="안녕"), AssistantMessage(content=[TextContent(text="안녕하세요")])]
    history += _success_history("두 번째 작업")
    spans = find_spans(history)
    assert [(s.start, s.request) for s in spans] == [(2, "두 번째 작업")]


# ── 초안 파싱 ─────────────────────────────────────────────────────────────────


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


def test_slugify_falls_back_when_nothing_remains():
    assert slugify("한국어 이름") == "procedure"
    assert slugify("a" * 80).startswith("a") and len(slugify("a" * 80)) == 40


def test_render_prompt_truncates_long_args():
    span = find_spans(_success_history())[0]
    long_step = span.steps[0].__class__("write_file", {"content": "x" * 1000})
    span = span.__class__(start=0, request=span.request, outcome=span.outcome, steps=(long_step,))
    prompt = render_prompt(span)
    assert "x" * 1000 not in prompt and "…" in prompt


# ── 저장소 ────────────────────────────────────────────────────────────────────


def test_store_roundtrip_and_upsert(tmp_path):
    store = ProcedureStore(str(tmp_path / "procs"))
    proc = Procedure(
        name="deploy", description="배포", body="절차:\n1. {{args}} 배포\n", source="s1#0", tools=("bash",)
    )
    store.save(proc)
    store.save(proc)  # 두 번 저장해도 파일 하나
    assert [p.name for p in store.list()] == ["deploy"]
    loaded = store.get("deploy")
    assert loaded == proc
    assert loaded.render("staging") == "절차:\n1. staging 배포\n"
    assert store.has_source("s1#0") and not store.has_source("s1#9")


def test_store_set_status_is_idempotent_and_delete(tmp_path):
    store = ProcedureStore(str(tmp_path))
    store.save(Procedure(name="x", description="d", body="b"))
    assert store.set_status("x", STATUS_APPROVED).approved
    mtime = (tmp_path / "x.md").stat().st_mtime_ns
    assert store.set_status("x", STATUS_APPROVED).approved
    assert (tmp_path / "x.md").stat().st_mtime_ns == mtime  # 같은 상태면 다시 쓰지 않는다
    assert store.set_status("nope", STATUS_DRAFT) is None
    with pytest.raises(ValueError):
        store.set_status("x", "weird")
    assert store.delete("x") is True
    assert store.delete("x") is False


def test_store_skips_unparseable_file(tmp_path, capsys):
    (tmp_path / "ok.md").write_text("---\nname: ok\ndescription: d\n---\nbody\n")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe")
    assert [p.name for p in ProcedureStore(str(tmp_path)).list()] == ["ok"]


# ── 학습기 ────────────────────────────────────────────────────────────────────


class _CountingDistiller:
    def __init__(self, draft: ProcedureDraft | None):
        self.draft = draft
        self.calls = 0

    async def __call__(self, span):
        self.calls += 1
        return self.draft


DRAFT = ProcedureDraft(
    name="run-tests",
    description="테스트 실행 후 요약",
    steps=("glob 로 테스트 찾기", "pytest 실행", "로그 읽기"),
    parameters="테스트 경로",
)


async def test_learn_twice_writes_once(tmp_path):
    store = ProcedureStore(str(tmp_path))
    distiller = _CountingDistiller(DRAFT)
    learner = ProcedureLearner(store, distiller)

    assert await learner.learn("s1", _success_history()) == ["run-tests"]
    assert await learner.learn("s1", _success_history()) == []
    assert distiller.calls == 1  # 같은 출처는 LLM 을 다시 부르지 않는다

    proc = store.get("run-tests")
    assert proc.status == STATUS_DRAFT
    assert proc.source == "s1#0"
    assert proc.tools == ("glob", "bash", "read_file")
    assert "{{args}}" in proc.body and "1. glob 로 테스트 찾기" in proc.body and "입력: 테스트 경로" in proc.body


async def test_learn_same_name_from_other_session_gets_suffix(tmp_path):
    store = ProcedureStore(str(tmp_path))
    learner = ProcedureLearner(store, _CountingDistiller(DRAFT))
    await learner.learn("s1", _success_history())
    written = await learner.learn("s2", _success_history())
    assert len(written) == 1 and written[0].startswith("run-tests-") and written[0] != "run-tests"
    assert len(store.list()) == 2


def test_unique_name_rules():
    assert unique_name("a", "s1#0", {}) == "a"
    assert unique_name("a", "s1#0", {"a": "s1#0"}) == "a"
    other = unique_name("a", "s2#0", {"a": "s1#0"})
    assert other.startswith("a-") and other == unique_name("a", "s2#0", {"a": "s1#0"})


async def test_learn_skips_when_distiller_fails(tmp_path):
    store = ProcedureStore(str(tmp_path))
    assert await ProcedureLearner(store, _CountingDistiller(None)).learn("s1", _success_history()) == []
    assert store.list() == []


# ── 도구와 스킬 노출 ─────────────────────────────────────────────────────────


async def test_procedure_tool_returns_rendered_recipe():
    proc = Procedure(name="deploy", description="배포", body="1. {{args}} 로 배포", parameters="환경 이름")
    tool = ProcedureTool(proc)
    assert tool.name == TOOL_PREFIX + "deploy"
    assert "배포" in tool.description and "환경 이름" in tool.description
    result = await tool.execute("id", {"args": "staging"})
    assert not result.is_error
    assert "1. staging 로 배포" in result.content[0].text


def test_register_approved_registers_only_approved_and_is_idempotent(tmp_path):
    store = ProcedureStore(str(tmp_path))
    store.save(Procedure(name="a", description="A", body="b", status=STATUS_APPROVED))
    store.save(Procedure(name="b", description="B", body="b"))
    tools, skills = ToolRegistry(), SkillRegistry()

    assert register_approved(store, tools, skills) == ["a"]
    assert register_approved(store, tools, skills) == ["a"]
    assert [t.name for t in tools.list_all()] == [TOOL_PREFIX + "a"]
    assert skills.get("a") is not None and skills.get("b") is None
    assert "b" in skills.expand("/a x")


# ── /procedures ───────────────────────────────────────────────────────────────


async def test_procedures_command_flow(tmp_path, jsonl_repo):
    store = ProcedureStore(str(tmp_path))
    tools, skills = ToolRegistry(), SkillRegistry()
    learner = ProcedureLearner(store, _CountingDistiller(DRAFT))
    await jsonl_repo.create(session_id="s1")
    for m in _success_history():
        await jsonl_repo.append("s1", m)
    handle = make_procedures_handler(store, tools, skills, learner=learner, session_repo=jsonl_repo, session_id="s1")

    assert "없습니다" in await handle("")
    assert "run-tests" in await handle("learn")
    assert "run-tests [draft]" in await handle("list")
    assert "pytest 실행" in await handle("show run-tests")
    assert "procedure_run-tests" in await handle("approve run-tests")
    assert tools.get("procedure_run-tests") is not None and skills.get("run-tests") is not None
    assert "없는 절차" in await handle("approve nope")
    assert "삭제" in await handle("reject run-tests")
    assert tools.get("procedure_run-tests") is None and skills.get("run-tests") is None
    assert "사용법" in await handle("bogus")


async def test_procedures_command_learn_disabled(tmp_path):
    handle = make_procedures_handler(ProcedureStore(str(tmp_path)), ToolRegistry(), SkillRegistry())
    assert "꺼져" in await handle("learn")
