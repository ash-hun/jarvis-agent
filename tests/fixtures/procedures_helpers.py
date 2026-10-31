"""procedures 테스트 공용: 도구 세 번 쓰고 성공한 대화, 세는 증류기, 턴 일화 기록."""

from datetime import datetime, timedelta

from jarvis.model_layer.model_types import AssistantMessage, TextContent, ToolCall, ToolResultMessage, UserMessage
from jarvis.core.procedures import ProcedureDraft, ProcedureLearner, ProcedureStore
from jarvis.memory.memory_service import MemoryService
from jarvis.memory import MemoryScope

DRAFT = ProcedureDraft(
    name="run-tests",
    description="테스트 실행 후 요약",
    steps=("glob 로 테스트 찾기", "pytest 실행", "로그 읽기"),
    parameters="테스트 경로",
)
PLAN_JSON = (
    '{"name": "run-tests", "description": "테스트 실행 후 요약", "steps": ["glob", "bash", "read"],'
    ' "inputs": ["test_dir", "log"],'
    ' "plan": [{"tool": "glob", "args": {"pattern": "{{test_dir}}/**/*.py"}},'
    ' {"tool": "bash", "args": {"command": "uv run pytest -q {{test_dir}}"}},'
    ' {"tool": "read_file", "args": {"path": "{{log}}"}}]}'
)
EDM_SCOPE = MemoryScope(user_id="u1", agent_id="karen", session_id="s1")
EDM_STEPS = [("lh_notice", {"region": "서울"}), ("housing_loan", {"price": 300_000_000})]
LOAN_DRAFT = ProcedureDraft(name="loan-from-notice", description="공고로 대출 계산", steps=("공고 조회", "대출 계산"))


def tool_turn(call_id: str, name: str, args: dict, is_error: bool = False) -> list:
    return [
        AssistantMessage(content=[ToolCall(id=call_id, name=name, arguments=args)], stop_reason="tool_use"),
        ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[TextContent(text="ok")], is_error=is_error),
    ]


def success_history(request: str = "테스트 돌리고 요약해줘") -> list:
    return [
        UserMessage(content=request),
        *tool_turn("c1", "glob", {"pattern": "tests/**/*.py"}),
        *tool_turn("c2", "bash", {"command": "uv run pytest -q"}),
        *tool_turn("c3", "read_file", {"path": "pytest.log"}),
        AssistantMessage(content=[TextContent(text="전부 통과했습니다.")], stop_reason="stop"),
    ]


class CountingDistiller:
    def __init__(self, draft: ProcedureDraft | None) -> None:
        self.draft = draft
        self.spans: list = []

    @property
    def calls(self) -> int:
        return len(self.spans)

    async def __call__(self, span):
        self.spans.append(span)
        return self.draft


async def record_turn(
    memory: MemoryService,
    index: int,
    task: str = "lh_notice",
    failed: bool = False,
    scope: MemoryScope = EDM_SCOPE,
    steps: list = EDM_STEPS,
) -> None:
    item_id = await memory.record_turn(
        index, f"서울 공고로 대출 계산 {index}", f"계산 결과 {index}", scope, task_type=task, failed=failed,
        tools=[n for n, _ in steps], steps=steps,
    )
    item = await memory.get(item_id)
    assert item is not None
    item.occurred_at = datetime(2026, 10, 1) + timedelta(days=index)
    await memory.store.store(item)


def edm_learner(tmp_path, memory: MemoryService) -> tuple[ProcedureLearner, ProcedureStore, CountingDistiller]:
    store = ProcedureStore(str(tmp_path))
    distiller = CountingDistiller(LOAN_DRAFT)
    return ProcedureLearner(store, distiller, memory=memory), store, distiller
