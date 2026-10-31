"""skills 기능: 스킬이 '/스킬 인자', 승인된 절차, 스케줄 작업, 절차 기억을 거쳐 모델에 닿는지 검증한다."""

import pytest
import asyncio
from pathlib import Path
from collections.abc import AsyncIterator

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamEvent, StreamOptions, UserMessage
from jarvis.core.procedures.procedures_store import STATUS_APPROVED, Procedure, ProcedureStore
from jarvis.core.procedures.tool import INSTRUCTION, TOOL_PREFIX, register_approved
from jarvis.memory.long_term.procedural import SkillRegistryProcedures
from jarvis.core.scheduler.scheduler_service import SchedulerService
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.core.slash.dispatcher import SlashCommandDispatcher
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import PROCEDURES_HEADER
from jarvis.memory.memory_service import MemoryService
from tests.fixtures.faux_provider import FauxProvider
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.session import AgentSession

REPO_SKILLS = Path(__file__).parents[2] / "skills"
PROVIDER = "skills-recording"
REPORT_SKILL = "---\nname: report\ndescription: 주간 보고\naliases: [rp]\n---\n{{args}} 기준으로 주간 보고를 써 줘"
REPLY = "알겠습니다"


class RecordingProvider(FauxProvider):
    """FauxProvider 처럼 답하고, 호출마다 모델이 받은 컨텍스트를 남긴다."""

    provider_name = PROVIDER

    def __init__(self) -> None:
        super().__init__(response=REPLY)
        self.contexts: list[LLMContext] = []

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.contexts.append(context.model_copy(deep=True))
        async for event in super().stream(model, context, options):
            yield event

    def user_texts(self) -> list[str]:
        """마지막 호출에서 모델이 받은 사용자 메시지 글."""
        return [_text(m) for m in self.contexts[-1].messages if isinstance(m, UserMessage)]


def _text(message: UserMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else "".join(getattr(c, "text", "") for c in content)


@pytest.fixture
def recorder() -> RecordingProvider:
    provider = RecordingProvider()
    registry = get_default_registry()
    registry._providers[PROVIDER] = provider
    yield provider
    registry._providers.pop(PROVIDER, None)


@pytest.fixture
def model() -> ModelConfig:
    return ModelConfig(provider=PROVIDER, model="faux-model")


@pytest.fixture
async def skills(tmp_path) -> SkillRegistry:
    user_dir = tmp_path / "skills"
    user_dir.mkdir()
    (user_dir / "report.md").write_text(REPORT_SKILL, encoding="utf-8")
    registry = SkillRegistry()
    await registry.load_directory(str(REPO_SKILLS))
    await registry.load_directory(str(user_dir))
    return registry


@pytest.fixture
def make_session(model, permissive_pipeline, plugin_runner, tool_registry, skills, jsonl_repo):
    async def make(memory: MemoryService | None = None) -> AgentSession:
        await jsonl_repo.create(session_id="test-session")
        return AgentSession(
            model=model,
            session_id="test-session",
            security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner,
            memory=memory or MemoryService(InMemoryItemStore()),
            tool_registry=tool_registry,
            skill_registry=skills,
            session_repo=jsonl_repo,
        )

    return make


async def _type(text: str, session: AgentSession, skills: SkillRegistry) -> str | None:
    """화면이 입력을 처리하는 순서: 슬래시 명령을 먼저 보고, 남은 글만 세션에 넣는다(ws_router, TUI 와 같다)."""
    result = await SlashCommandDispatcher(skill_registry=skills).dispatch(text, session.memory_scope)
    if result.fully_consumed:
        return "\n".join(result.feedbacks)
    reply = await session.prompt(result.remaining_text)
    return reply.text() if reply is not None else None


async def test_slash_skill_expands_into_the_prompt_the_model_receives(make_session, skills, recorder, jsonl_repo):
    session = await make_session()

    reply = await _type("/test -k foo", session, skills)

    received = recorder.user_texts()[-1]
    assert received == skills.get("test").content.replace("{{args}}", "-k foo")
    assert "uv run pytest tests/unit/ -v --no-header --tb=short -k foo" in received
    assert "/test" not in received and "{{args}}" not in received
    assert reply is not None and REPLY in reply
    stored = [_text(m) for m in await jsonl_repo.get_messages("test-session") if isinstance(m, UserMessage)]
    assert stored == [received]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("/ut -k bar", "--tb=short -k bar"), ("/rp 이번 주", "이번 주 기준으로 주간 보고를 써 줘")],
)
async def test_slash_alias_expands_like_the_skill_name(make_session, skills, recorder, text, expected):
    session = await make_session()

    await _type(text, session, skills)

    assert expected in recorder.user_texts()[-1]


async def test_unknown_slash_name_is_not_expanded_as_a_skill(make_session, skills, recorder):
    session = await make_session()

    feedback = await _type("/nosuch 인자", session, skills)
    await session.prompt("/nosuch 인자")

    assert "알 수 없는 명령: /nosuch" in feedback
    assert len(recorder.contexts) == 1
    assert recorder.user_texts()[-1] == "/nosuch 인자"


async def test_approved_procedure_reaches_the_model_as_skill_and_tool(
    make_session, skills, recorder, tool_registry, tmp_path
):
    store = ProcedureStore(str(tmp_path / "procedures"))
    store.save(Procedure(name="weekly-report", description="주간 보고", body="1. 커밋을 모은다\n2. 요약한다",
                         status=STATUS_APPROVED))
    store.save(Procedure(name="draft-only", description="초안", body="아직"))

    assert register_approved(store, tool_registry, skills) == ["weekly-report"]
    session = await make_session()
    await _type("/weekly-report", session, skills)

    assert recorder.user_texts()[-1] == INSTRUCTION + store.get("weekly-report").body
    assert "1. 커밋을 모은다\n2. 요약한다" in recorder.user_texts()[-1]
    assert TOOL_PREFIX + "weekly-report" in {t.name for t in recorder.contexts[-1].tools or []}
    assert skills.get("draft-only") is None


async def test_scheduled_task_prompt_expands_the_skill(model, skills, recorder, jsonl_repo, tool_registry):
    delivered: asyncio.Queue[dict] = asyncio.Queue()
    service = SchedulerService([], jsonl_repo, tool_registry, model, skill_registry=skills)

    async def notify(payload: dict) -> None:
        await delivered.put(payload)

    service.set_notifier(notify)
    service.run_soon(ScheduledTask(name="nightly", prompt="/test -k nightly"))
    payload = await asyncio.wait_for(delivered.get(), timeout=5.0)

    assert "--tb=short -k nightly" in recorder.user_texts()[-1]
    assert payload["error"] is False and REPLY in payload["text"]


async def test_skill_named_in_plain_words_is_offered_as_procedural_memory(make_session, skills, recorder):
    memory = MemoryService(InMemoryItemStore(), procedures=SkillRegistryProcedures(skills))
    session = await make_session(memory)

    await session.prompt("report 좀 부탁해")

    texts = recorder.user_texts()
    assert any(t.startswith(PROCEDURES_HEADER) and "- /report: 주간 보고" in t for t in texts)
    assert texts[-1] == "report 좀 부탁해"
