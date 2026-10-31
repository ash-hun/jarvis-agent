"""공통 테스트 fixture. 모든 테스트는 실 API 없이 FauxProvider 로 돈다."""
import os
import sys
import pytest
import socket
from pathlib import Path

# src/ 를 import 경로에 추가 (Docker 외 로컬 실행 대비)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 환경변수 강제 설정 (테스트 전 config 오염 방지)
os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LLM__MODEL", "faux-model")
os.environ.setdefault("JARVIS_MEMORY__BACKEND", "in_memory")
os.environ.setdefault("JARVIS_SECURITY__REQUIRE_AUTH", "false")
# 개발자의 ~/.jarvis/team 이 테스트 앱에 에이전트를 더하지 않게. 팀 테스트는 monkeypatch 로 디렉터리를 준다
os.environ.setdefault("JARVIS_TEAM__DIR", str(Path(__file__).parent / "fixtures" / "no-team"))

# 개발자의 로컬 .env 가 테스트 기본값을 덮지 않게. 테스트는 환경변수와 monkeypatch 로만 설정을 바꾼다
from jarvis.jarvis_config import JarvisSettings  # noqa: E402

JarvisSettings.model_config["env_file"] = None


# ── 외부 네트워크 차단 ─────────────────────────────────────────────────────────

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _guard(address: object) -> None:
    # 유닉스 소켓(asyncio 내부 socketpair)과 로컬 테스트 DB 는 허용한다. 그 밖은 외부 API 라 mock 이어야 한다
    if isinstance(address, tuple) and address and str(address[0]) not in LOOPBACK_HOSTS:
        raise RuntimeError(f"테스트가 외부 네트워크로 나가려 했다: {address!r}")


def _guarded_connect(self: socket.socket, address: object) -> None:
    _guard(address)
    _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    _guard(address)
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


# ── FauxProvider를 ProviderRegistry에 등록 ─────────────────────────────────────

@pytest.fixture(autouse=True)
def register_faux_provider():
    """모든 테스트에 자동 적용 — FauxProvider를 레지스트리에 등록."""
    from jarvis.model_layer.model_registry import get_default_registry
    from tests.fixtures.faux_provider import FauxProvider

    registry = get_default_registry()
    if "faux" not in registry.list_names():
        registry.register(FauxProvider())
    yield
    # teardown: config 싱글톤 초기화
    from jarvis.jarvis_config import reset_settings
    reset_settings()


# ── ModelConfig fixture ────────────────────────────────────────────────────────

@pytest.fixture
def faux_model():
    from jarvis.model_layer.model_types import ModelConfig
    return ModelConfig(provider="faux", model="faux-model")


@pytest.fixture
def faux_model_with_response():
    """특정 응답을 반환하는 faux model — registry를 교체."""
    def _factory(response: str = "Hello!", tool_calls: list | None = None):
        from jarvis.model_layer.model_registry import get_default_registry
        from jarvis.model_layer.model_types import ModelConfig
        from tests.fixtures.faux_provider import FauxProvider

        registry = get_default_registry()
        registry._providers["faux"] = FauxProvider(response=response, tool_calls=tool_calls)
        return ModelConfig(provider="faux", model="faux-model")
    return _factory


# ── SecurityPipeline fixture ───────────────────────────────────────────────────

@pytest.fixture
def permissive_pipeline():
    """인증/권한 검사 없이 모두 통과하는 파이프라인."""
    from jarvis.core.policy.authenticator import NoAuthAuthenticator
    from jarvis.core.policy.validator import DefaultInputValidator
    from jarvis.core.policy.pipeline import SecurityPipeline
    from jarvis.core.policy.sandbox import PermissiveSandbox
    from jarvis.core.policy.policy import AllowAllPolicy

    return SecurityPipeline(
        validator=DefaultInputValidator(),
        authenticator=NoAuthAuthenticator(),
        policy=AllowAllPolicy(),
        sandbox=PermissiveSandbox(),
    )


# ── Session + repo fixture ─────────────────────────────────────────────────────

@pytest.fixture
def tmp_session_dir(tmp_path):
    return str(tmp_path / "sessions")


@pytest.fixture
def jsonl_repo(tmp_session_dir):
    from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
    return JsonlSessionRepo(sessions_root=tmp_session_dir)


@pytest.fixture
def session_memory():
    from jarvis.memory.stores.in_memory import InMemoryItemStore
    from jarvis.memory.memory_service import MemoryService
    return MemoryService(InMemoryItemStore())


@pytest.fixture
def tool_registry():
    from jarvis.core.tools.tools_registry import ToolRegistry
    return ToolRegistry()


@pytest.fixture
def skill_registry():
    from jarvis.core.skills.skills_registry import SkillRegistry
    return SkillRegistry()


@pytest.fixture
def plugin_runner():
    from jarvis.core.plugins.runner import PluginRunner
    return PluginRunner()


@pytest.fixture
async def agent_session(
    faux_model,
    permissive_pipeline,
    plugin_runner,
    session_memory,
    tool_registry,
    skill_registry,
    jsonl_repo,
    tmp_session_dir,
):
    """전체 레이어가 연결된 AgentSession (faux provider 사용)."""
    from jarvis.core.session import AgentSession

    await jsonl_repo.create(session_id="test-session")

    return AgentSession(
        model=faux_model,
        session_id="test-session",
        security_pipeline=permissive_pipeline,
        plugin_runner=plugin_runner,
        memory=session_memory,
        tool_registry=tool_registry,
        skill_registry=skill_registry,
        session_repo=jsonl_repo,
    )


# ── 청약 게시판 fixture ────────────────────────────────────────────────────────

@pytest.fixture
def lh_board():
    from tests.fixtures.housing_board import FakeBoard, page
    return FakeBoard({"selectWrtancList.do": page("lh_list.html"), "selectWrtancInfo.do": page("lh_detail_sale.html")})


@pytest.fixture
def sh_board():
    from tests.fixtures.housing_board import FakeBoard, page
    return FakeBoard({"list.do": page("sh_list.html"), "view.do": page("sh_detail.html")})
