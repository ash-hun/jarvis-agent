"""[scripts] 각본 모델로 한 턴을 돌려 보안, 기억, 저장, 이벤트 단계가 모델 밖에서 쓰는 시간을 설정별로 잰다."""

import os
import sys
import json
import time
import asyncio
import argparse
import tempfile
import statistics
from typing import Any
from pathlib import Path
from collections.abc import AsyncIterator, Awaitable, Callable

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.model_layer.model_types import (
    LLMContext,
    Message,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    Usage,
)
from jarvis.agent_layer.session.session_protocol import SessionEntry, SessionMetadata, SessionRepo
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.core.policy.authenticator import NoAuthAuthenticator
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.core.policy.pipeline import SecurityPipeline
from jarvis.core.policy.sandbox import PermissiveSandbox
from jarvis.memory.memory_service import MemoryService
from jarvis.core.policy.policy import AllowAllPolicy
from jarvis.core.plugins.runner import PluginRunner
from jarvis.core.session import AgentSession
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "turn_overhead"
TURNS = 200  # 세션 하나에 이어 붙이는 턴 수
SESSIONS = 3  # 설정마다 새 세션을 이만큼 돌린다
WINDOWS = {"turns_1_20": (0, 20), "turns_181_200": (180, 200)}
PROVIDER = "turn_script"
REPLY = "네, 오늘 할 일을 세 줄로 정리했어요."
CONFIGS = {
    "jsonl_memory_on": ("jsonl", True),
    "jsonl_memory_off": ("jsonl", False),
    "dict_memory_on": ("dict", True),
}
STAGES = ("security", "memory_observe", "memory_reinforce", "repo_read", "repo_write", "events", "model")


class ScriptModel:
    """바로 답하는 각본 모델. 모델 시간은 0 에 가깝게 두고 따로 잰다."""

    provider_name = PROVIDER

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        for word in REPLY.split():
            yield TextDeltaEvent(delta=word + " ")
        yield StopEvent(reason="stop", usage=Usage(input=10, output=5))


class DictSessionRepo(SessionRepo):
    """파일 I/O 없이 메모리 list 에 두는 저장소. JSONL 저장 비용을 떼어 보려는 비교군이다."""

    def __init__(self) -> None:
        self._messages: dict[str, list[Message]] = {}
        self._metas: dict[str, SessionMetadata] = {}
        self._proactive: dict[str, list[SessionEntry]] = {}

    async def create(self, session_id: str | None = None, cwd: str = ".", agent_id: str = "main") -> SessionMetadata:
        sid = session_id or self._new_id()
        now = self._now_ms()
        meta = self._metas.setdefault(
            sid,
            SessionMetadata(
                session_id=sid, created_at=now, updated_at=now, cwd=cwd, agent_id=agent_id, message_count=0
            ),
        )
        self._messages.setdefault(sid, [])
        return meta

    async def get_meta(self, session_id: str) -> SessionMetadata | None:
        return self._metas.get(session_id)

    async def get_messages(self, session_id: str) -> list[Message]:
        return list(self._messages.get(session_id, []))

    async def append(self, session_id: str, message: Message) -> str:
        self._messages.setdefault(session_id, []).append(message)
        return self._new_id()

    async def get_proactive(self, session_id: str, entry_type: str = "proactive") -> list[SessionEntry]:
        return list(self._proactive.get(session_id, []))


class StageTimer:
    """인스턴스 메서드를 감싸 단계별 누적 시간을 잰다. 단계들은 서로 겹치지 않는 잎 호출이다."""

    def __init__(self) -> None:
        self.spent: dict[str, float] = dict.fromkeys(STAGES, 0.0)

    def wrap(self, owner: Any, method: str, stage: str) -> None:
        inner: Callable[..., Awaitable[Any]] = getattr(owner, method)

        async def timed(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await inner(*args, **kwargs)
            finally:
                self.spent[stage] += time.perf_counter() - start

        setattr(owner, method, timed)

    def wrap_stream(self, provider: ScriptModel) -> None:
        inner = provider.stream
        timer = self

        def timed(model: ModelConfig, context: LLMContext, options: StreamOptions | None = None) -> Any:
            gen = inner(model, context, options)

            async def run() -> AsyncIterator[StreamEvent]:
                while True:
                    start = time.perf_counter()
                    try:
                        event = await gen.__anext__()
                    except StopAsyncIteration:
                        timer.spent["model"] += time.perf_counter() - start
                        return
                    timer.spent["model"] += time.perf_counter() - start
                    yield event

            return run()

        provider.stream = timed  # type: ignore[method-assign]

    def reset(self) -> None:
        self.spent = dict.fromkeys(STAGES, 0.0)


def _session(repo: SessionRepo, memory: MemoryService | None, sid: str) -> AgentSession:
    return AgentSession(
        model=ModelConfig(provider=PROVIDER, model="script"),
        session_id=sid,
        security_pipeline=SecurityPipeline(
            validator=DefaultInputValidator(), authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(), sandbox=PermissiveSandbox(),
        ),
        plugin_runner=PluginRunner(),
        memory=memory,
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        session_repo=repo,
    )


async def run_session(config: str, index: int, root: str, timer: StageTimer) -> list[dict[str, float]]:
    backend, memory_on = CONFIGS[config]
    repo: SessionRepo = (
        JsonlSessionRepo(sessions_root=f"{root}/{config}-{index}") if backend == "jsonl" else DictSessionRepo()
    )
    memory = MemoryService(InMemoryItemStore()) if memory_on else None
    sid = f"{config}-{index}"
    await repo.create(session_id=sid)
    session = _session(repo, memory, sid)
    for method in ("get_messages", "get_proactive", "get_meta"):
        timer.wrap(repo, method, "repo_read")
    timer.wrap(repo, "append", "repo_write")
    if memory is not None:
        timer.wrap(memory, "observe", "memory_observe")
        timer.wrap(memory, "reinforce", "memory_reinforce")
    timer.wrap(session._security, "run", "security")
    timer.wrap(session._harness, "_emit", "events")

    async def listener(event: Any) -> None:
        return None

    session.subscribe(listener)  # 화면 하나가 붙은 것처럼(Web 은 이벤트를 WebSocket 으로 흘린다)
    rows = []
    for turn in range(TURNS):
        timer.reset()
        start = time.perf_counter()
        await session.prompt(f"오늘 할 일 {turn}번 정리해 줘")
        total = time.perf_counter() - start
        rows.append({"total": total, **timer.spent})
    return rows


def _window(rows: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for field in ("total", *STAGES):
        out[f"{field}_ms"] = round(statistics.median(r[field] for r in rows) * 1000, 3)
    others = [r["total"] - sum(r[s] for s in STAGES) for r in rows]
    out["other_ms"] = round(statistics.median(others) * 1000, 3)
    out["framework_ms"] = round(statistics.median(r["total"] - r["model"] for r in rows) * 1000, 3)
    return out


async def measure() -> dict[str, Any]:
    model = ScriptModel()
    get_default_registry().register(model)
    timer = StageTimer()
    timer.wrap_stream(model)
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as root:
        # 첫 import 와 캐시가 첫 설정에만 붙지 않게 버리는 세션 하나
        await run_session("dict_memory_on", -1, root, timer)
        for config in CONFIGS:
            sessions = [await run_session(config, i, root, timer) for i in range(SESSIONS)]
            result[config] = {
                name: _window([row for rows in sessions for row in rows[lo:hi]]) for name, (lo, hi) in WINDOWS.items()
            }
    result["turns_per_session"] = TURNS
    result["sessions"] = SESSIONS
    return result


def write(result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    result = asyncio.run(measure())
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if not args.dry_run:
        write(result)


if __name__ == "__main__":
    main()
