"""[scripts] 외부 이벤트가 상한 초과와 사고 실패 속에서 몇 건이나 먼저 건넨 말까지 닿는지 세어 results.json 에 쓴다."""

import os
import sys
import json
import time
import random
import asyncio
import argparse
import tempfile
import statistics
from typing import Any
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LLM__MODEL", "faux-model")
os.environ.setdefault("JARVIS_MEMORY__BACKEND", "in_memory")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.core.external import ExternalEvent, ExternalEventInbox, ExternalEventPoller, InMemorySeenStore
from jarvis.core.proactive import DefaultProactivityCore, DefaultProactivityPolicy
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.model_layer.model_types import ModelConfig, UserMessage
from jarvis.core.external.external_protocol import ExternalSource
from jarvis.core.policy.authenticator import NoAuthAuthenticator
from jarvis.core.policy.validator import DefaultInputValidator
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore
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
import jarvis.core.session as session_module
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "external_delivery"
CAP = 20  # ExternalEventPoller 의 기본 max_events_per_tick
POLL_SEC = 300.0  # 외부 소스 기본 주기
REFLECT_SEC = 120.0  # proactive.daemon_interval_sec 기본값
PRODUCE_POLLS = 24  # 새 이벤트가 오는 조회 수(2시간)
DRAIN_POLLS = 24  # 그 뒤 새 이벤트 없이 기다리는 조회 수
SEEDS = 10
# window 는 소스 목록에 남는 최근 아이템 수. 조회 세 번(15분) 동안 남거나, 폭주는 받은 편지함 첫 화면(60건)
SCENARIOS = {
    "steady_5": {"burst": 0, "per_poll": 5, "window": 15},
    "burst_50": {"burst": 50, "per_poll": 0, "window": 60},
    "overload_30": {"burst": 0, "per_poll": 30, "window": 90},
}
FAIL_RATES = (0.0, 0.2, 0.5)
HANGUL = [chr(c) for c in range(0xAC00, 0xD7A4)]


class SimClock:
    """경계에서 만든 가짜 시각. 폴러, 세션의 성찰 키, seen 저장소가 같은 시각을 본다."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class WindowSource(ExternalSource):
    """조회마다 새 아이템을 만들고 가장 최근 window 건을 목록으로 준다(MCP 의 최근 메일 조회처럼)."""

    def __init__(self, burst: int, per_poll: int, window: int) -> None:
        super().__init__(name="mail", interval_sec=POLL_SEC)
        self._burst = burst
        self._per_poll = per_poll
        self._window = window
        self._polls = 0
        self.created: list[str] = []

    async def poll(self) -> list[ExternalEvent]:
        self._polls += 1
        count = 0
        if self._polls <= PRODUCE_POLLS:
            count = self._per_poll + (self._burst if self._polls == 1 else 0)
        for _ in range(count):
            self.created.append(f"mail:{len(self.created):04d}")
        return [ExternalEvent(source=self.name, key=k, title=k) for k in self.created[-self._window:]]


class FlakyEngine:
    """사고 모델 대역. fail_rate 확률로 실패(None)하고, 아니면 받은 이벤트를 전부 말하겠다고 한다."""

    def __init__(self, fail_rate: float, rng: random.Random) -> None:
        self._fail = fail_rate
        self._rng = rng
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        if self._rng.random() < self._fail:
            return None
        # 최근 건넨 말과 겹친다는 판정(same_loop)을 피하려 매번 다른 무작위 한글로 말한다
        utterance = "".join(self._rng.choice(HANGUL) for _ in range(16))
        return ThoughtFrame(decision="act", confidence=0.9, utterance=utterance)


def _pipeline() -> SecurityPipeline:
    return SecurityPipeline(
        validator=DefaultInputValidator(),
        authenticator=NoAuthAuthenticator(),
        policy=AllowAllPolicy(),
        sandbox=PermissiveSandbox(),
    )


async def simulate(scenario: str, fail_rate: float, seed: int, root: str) -> dict[str, int]:
    clock = SimClock()
    real_time = session_module.time
    # 성찰 키의 REFLECT_REFRESH_SEC 버킷이 가짜 시각을 따르게 세션 모듈의 time 만 바꾼다
    session_module.time = SimpleNamespace(  # type: ignore[assignment]
        time=clock, monotonic=real_time.monotonic, perf_counter=real_time.perf_counter
    )
    try:
        return await _simulate(clock, scenario, fail_rate, seed, root)
    finally:
        session_module.time = real_time  # type: ignore[assignment]


async def _simulate(clock: SimClock, scenario: str, fail_rate: float, seed: int, root: str) -> dict[str, int]:
    rng = random.Random(seed)
    source = WindowSource(**SCENARIOS[scenario])
    inbox = ExternalEventInbox()
    poller = ExternalEventPoller([source], inbox, InMemorySeenStore(clock=clock), max_events_per_tick=CAP, clock=clock)
    repo = JsonlSessionRepo(sessions_root=f"{root}/{scenario}-{fail_rate}-{seed}")
    sid = "s1"
    await repo.create(session_id=sid)
    await repo.append(sid, UserMessage(content="안녕"))
    cores: list[DefaultProactivityCore] = []

    def factory(emit: Any) -> DefaultProactivityCore:
        core = DefaultProactivityCore(
            emit_proactive=emit, policy=DefaultProactivityPolicy(confidence_threshold=0.5, cooldown_sec=0)
        )
        cores.append(core)
        return core

    engine = FlakyEngine(fail_rate, rng)
    session = AgentSession(
        model=ModelConfig(provider="faux", model="faux-model"),
        session_id=sid,
        security_pipeline=_pipeline(),
        plugin_runner=PluginRunner(),
        memory=MemoryService(InMemoryItemStore()),
        tool_registry=ToolRegistry(),
        skill_registry=SkillRegistry(),
        session_repo=repo,
        thought_engine=engine,
        proactivity_factory=factory,
        external_inbox=inbox,
        openloop_store=InMemoryOpenLoopStore(),
    )
    spoken: dict[str, int] = {}
    reflects = int((PRODUCE_POLLS + DRAIN_POLLS) * POLL_SEC / REFLECT_SEC)
    for _ in range(reflects):
        await poller.tick()
        asked = len(engine.requests)
        decision = await session.reflect()
        if decision is not None and decision.speak and len(engine.requests) > asked:
            for line in engine.requests[-1].external_events:
                key = line.split("] ", 1)[1].split()[0]
                spoken[key] = spoken.get(key, 0) + 1
            # 사용자가 바로 답했다고 둔다. 답 대기 게이트가 다음 말을 막지 않게(손실을 고친 부분에만 돌리려고)
            cores[0].note_user_activity(sid)
        clock.now += REFLECT_SEC
    delivered = sum(1 for k in source.created if k in spoken)
    return {
        "created": len(source.created),
        "delivered": delivered,
        "duplicates": sum(n - 1 for n in spoken.values() if n > 1),
        "thought_calls": len(engine.requests),
    }


async def measure() -> dict[str, Any]:
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as root:
        for scenario in SCENARIOS:
            rows = []
            for rate in FAIL_RATES:
                runs = [await simulate(scenario, rate, seed, root) for seed in range(SEEDS)]
                created = sum(r["created"] for r in runs)
                delivered = sum(r["delivered"] for r in runs)
                rows.append({
                    "fail_rate": rate,
                    "created": created,
                    "delivered": delivered,
                    "loss_rate": round(1 - delivered / created, 3),
                    "loss_min": round(min(1 - r["delivered"] / r["created"] for r in runs), 3),
                    "loss_max": round(max(1 - r["delivered"] / r["created"] for r in runs), 3),
                    "duplicates": sum(r["duplicates"] for r in runs),
                    "thought_calls_mean": round(statistics.mean(r["thought_calls"] for r in runs), 1),
                })
            result[scenario] = rows
    result["seeds"] = SEEDS
    return result


def write(label: str, result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {})[label] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="results.json 의 external_delivery 아래 키(코드 시점)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    start = time.perf_counter()
    result = asyncio.run(measure())
    print(json.dumps(result, ensure_ascii=False))
    print(f"took {time.perf_counter() - start:.1f}s", file=sys.stderr)
    if not args.dry_run:
        write(args.label, result)


if __name__ == "__main__":
    main()
