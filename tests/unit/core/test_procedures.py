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
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolCall, ToolResultMessage, UserMessage
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.procedures.distill import render_prompt, slugify
from jarvis.core.procedures.learner import unique_name
from jarvis.core.skills.registry import SkillRegistry
from jarvis.core.tools.registry import ToolRegistry

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


def test_find_spans_keeps_recovered_task_without_the_failed_call():
    history = [
        UserMessage(content="테스트 돌리고 요약해줘"),
        *_tool_turn("c1", "glob", {"pattern": "tests/**/*.py"}),
        *_tool_turn("c2", "bash", {"command": "pytest -q"}, is_error=True),
        *_tool_turn("c3", "bash", {"command": "uv run pytest -q"}),
        *_tool_turn("c4", "read_file", {"path": "pytest.log"}),
        AssistantMessage(content=[TextContent(text="전부 통과했습니다.")], stop_reason="stop"),
    ]
    [span] = find_spans(history)
    # 실패한 호출은 절차에 남기지 않는다. 배울 것은 성공한 경로다
    assert [(s.name, s.args) for s in span.steps] == [
        ("glob", {"pattern": "tests/**/*.py"}),
        ("bash", {"command": "uv run pytest -q"}),
        ("read_file", {"path": "pytest.log"}),
    ]
    # 실패 뒤 같은 도구가 다시 성공하지 않았으면 회복이 아니다
    unrecovered = history[:3] + history[5:7] + _tool_turn("c5", "bash", {"command": "x"}, is_error=True) + history[-1:]
    assert find_spans(unrecovered) == []


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


# ── 실행 계획 ─────────────────────────────────────────────────────────────────

PLAN_JSON = (
    '{"name": "run-tests", "description": "테스트 실행 후 요약", "steps": ["glob", "bash", "read"],'
    ' "inputs": ["test_dir", "log"],'
    ' "plan": [{"tool": "glob", "args": {"pattern": "{{test_dir}}/**/*.py"}},'
    ' {"tool": "bash", "args": {"command": "uv run pytest -q {{test_dir}}"}},'
    ' {"tool": "read_file", "args": {"path": "{{log}}"}}]}'
)


def test_learned_plan_survives_only_when_it_uses_the_task_tools_and_inputs(tmp_path):
    from dataclasses import replace

    from jarvis.core.procedures.learner import build_procedure
    from jarvis.core.procedures.plan import PlanStep

    draft = parse_draft(PLAN_JSON)
    assert draft is not None and draft.inputs == ("test_dir", "log") and len(draft.plan) == 3
    span = find_spans(_success_history())[0]
    proc = build_procedure(draft, span, "s1#0", "run-tests")
    assert proc.plan == draft.plan
    store = ProcedureStore(str(tmp_path))
    store.save(proc)
    assert store.get("run-tests") == proc  # 계획도 파일로 왕복한다

    foreign = replace(draft, plan=(*draft.plan, PlanStep("write_file", {"path": "x"})))
    assert build_procedure(foreign, span, "s1#0", "x").plan == ()  # 작업에서 쓰지 않은 도구
    unknown = replace(draft, plan=(PlanStep("glob", {"pattern": "{{nope}}"}),))
    assert build_procedure(unknown, span, "s1#0", "x").plan == ()  # 선언하지 않은 입력
    assert parse_draft(PLAN_JSON.replace('"args": {"path": "{{log}}"}', '"args": "x"')).plan == ()  # 반쪽 계획


class _Session:
    """세션 실행기 흉내. 받은 호출을 남기고 deny 에 든 도구는 승인 거절로 답한다."""

    def __init__(self, deny: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.deny = deny

    async def __call__(self, call_id, name, args):
        self.calls.append((call_id, name, args))
        denied = name in self.deny
        return ToolResultMessage(
            tool_call_id=call_id, tool_name=name, content=[TextContent(text="거절" if denied else f"{name} ok")],
            is_error=denied,
        )


async def test_procedure_with_plan_runs_each_step_through_the_session_executor():
    from jarvis.core.tools.registry import ToolContext

    draft = parse_draft(PLAN_JSON)
    proc = Procedure(name="run-tests", description="d", body="b", inputs=draft.inputs, plan=draft.plan)
    session = _Session()
    tool = ProcedureTool(proc)
    assert tool.parameters["properties"]["inputs"]["required"] == ["test_dir", "log"]

    result = await tool.execute("t1", {"inputs": {"test_dir": "tests", "log": "out.log"}}, context=ToolContext(
        scope=None, call=session
    ))
    assert not result.is_error
    assert session.calls == [
        ("t1-1", "glob", {"pattern": "tests/**/*.py"}),
        ("t1-2", "bash", {"command": "uv run pytest -q tests"}),
        ("t1-3", "read_file", {"path": "out.log"}),
    ]

    # 승인이 거절되면 그 단계에서 멈춘다
    refused = _Session(deny=("bash",))
    stopped = await tool.execute("t2", {"inputs": {"test_dir": "tests", "log": "o"}}, context=ToolContext(
        scope=None, call=refused
    ))
    assert stopped.is_error and [c[1] for c in refused.calls] == ["glob", "bash"]
    assert "2단계에서 멈췄다" in stopped.content[0].text

    # 입력이 빠졌거나 세션 실행기가 없으면 실행하지 않고 레시피를 돌려준다
    missing = _Session()
    recipe = await tool.execute("t3", {"inputs": {"test_dir": "tests"}}, context=ToolContext(scope=None, call=missing))
    assert missing.calls == [] and "절차를 순서대로" in recipe.content[0].text
    assert "절차를 순서대로" in (await tool.execute("t4", {"inputs": {"test_dir": "a", "log": "b"}})).content[0].text


class _Recorder:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.parameters, self.execution_mode = name, name, {}, "parallel"
        self.ran: list[dict] = []

    async def execute(self, tool_call_id, params, signal=None):
        self.ran.append(params)
        return ToolResultMessage(tool_call_id=tool_call_id, tool_name=self.name, content=[TextContent(text="ok")])


async def test_procedure_steps_in_a_real_session_still_need_approval(
    faux_model, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
):
    from jarvis.core.policy.pipeline import AuthContext, PolicyResult, SecurityPipeline
    from jarvis.core.policy.authenticator import NoAuthAuthenticator
    from jarvis.core.policy.validator import DefaultInputValidator
    from jarvis.core.policy.sandbox import DefaultSandbox
    from jarvis.core.policy.policy import AllowAllPolicy
    from jarvis.core.procedures.plan import PlanStep
    from jarvis.core.session import AgentSession

    glob, bash = _Recorder("glob"), _Recorder("bash")
    tool_registry.register(glob)
    tool_registry.register(bash)
    plan = (PlanStep("glob", {"pattern": "{{p}}"}), PlanStep("bash", {"command": "echo {{p}}"}))
    tool_registry.register(ProcedureTool(Procedure(name="x", description="d", body="b", inputs=("p",), plan=plan)))
    # 승인 화면이 없으면 bash 는 거절된다. 절차 안의 bash 도 같은 검사를 받아야 한다
    pipeline = SecurityPipeline(
        validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(), policy=AllowAllPolicy(),
        sandbox=DefaultSandbox(require_approval_for=["bash"]),
    )
    session = AgentSession(
        model=faux_model, session_id="s", security_pipeline=pipeline, plugin_runner=plugin_runner,
        memory=session_memory, tool_registry=tool_registry, skill_registry=skill_registry, session_repo=jsonl_repo,
    )
    executor = session._make_tool_executor(
        AuthContext(user_id="u", roles=frozenset()), PolicyResult(frozenset({"*"}), frozenset({"*"}))
    )
    result = await executor("t1", TOOL_PREFIX + "x", {"inputs": {"p": "*.md"}})
    assert glob.ran == [{"pattern": "*.md"}]
    assert bash.ran == []
    assert result.is_error and "2단계에서 멈췄다" in result.content[0].text
