"""[scripts] 같은 세션 id 의 삭제와 열기를 무작위로 겹쳐, 저장소에선 지워졌는데 살아 있는 세션 수를 센다."""

import os
import sys
import json
import random
import asyncio
import argparse
from typing import Any
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from collections.abc import Awaitable

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.ui.web.session_registry import SessionRegistry
from jarvis.jarvis_config import JarvisSettings
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "session_race"
TRIALS = 2000
MAX_YIELDS = 3  # 저장소와 기억 호출마다 끼우는 await 수(0~3). 실제 파일, DB 왕복이 이벤트 루프를 내주는 자리
SEED = 7

JarvisSettings.model_config["env_file"] = None


class JitterRepo:
    """세션 저장소 대역. 메모리 dict 이고, 호출마다 시드로 정한 횟수만큼 이벤트 루프를 내준다."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.metas: dict[str, str] = {}

    async def _yield(self) -> None:
        for _ in range(self._rng.randint(0, MAX_YIELDS)):
            await asyncio.sleep(0)

    async def get_meta(self, session_id: str) -> Any:
        await self._yield()
        agent = self.metas.get(session_id)
        return None if agent is None else SimpleNamespace(agent_id=agent)

    async def create(self, session_id: str, agent_id: str = "main") -> None:
        await self._yield()
        self.metas.setdefault(session_id, agent_id)
        await self._yield()

    async def delete(self, session_id: str) -> None:
        await self._yield()
        self.metas.pop(session_id, None)


class JitterMemory:
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng

    async def forget_session(self, session_id: str) -> None:
        for _ in range(self._rng.randint(0, MAX_YIELDS)):
            await asyncio.sleep(0)


class Agents:
    main = SimpleNamespace(agent_id="main")

    def __contains__(self, agent_id: str) -> bool:
        return agent_id == "main"

    def approval_rules(self, agent_id: str) -> list[Any]:
        return []

    def builder(self, agent_id: str) -> SimpleNamespace:
        return SimpleNamespace(build=lambda session_id, services, inherit_scope=False: MagicMock(name=session_id))


async def _after(yields: int, op: Awaitable[Any]) -> Any:
    for _ in range(yields):
        await asyncio.sleep(0)
    return await op


async def measure() -> dict[str, Any]:
    rng = random.Random(SEED)
    repo = JitterRepo(rng)
    services = MagicMock()
    services.memory = JitterMemory(rng)
    services.with_security = lambda pipeline, sandbox: services
    ctx = SimpleNamespace(settings=JarvisSettings(), session_repo=repo)
    registry = SessionRegistry(ctx, services, Agents())  # type: ignore[arg-type]
    outcomes = {"both_gone": 0, "both_alive": 0, "alive_without_history": 0, "history_without_session": 0}
    for i in range(TRIALS):
        sid = f"s{i}"
        await registry.get_or_create(sid)
        # 화면의 삭제 요청과, 같은 세션으로 다시 붙는 WebSocket 이 거의 동시에 온다
        await asyncio.gather(
            _after(rng.randint(0, MAX_YIELDS), registry.remove(sid)),
            _after(rng.randint(0, MAX_YIELDS), registry.get_or_create(sid)),
        )
        alive, stored = sid in registry.list_ids(), sid in repo.metas
        if alive and stored:
            outcomes["both_alive"] += 1
        elif not alive and not stored:
            outcomes["both_gone"] += 1
        elif alive:
            outcomes["alive_without_history"] += 1
        else:
            outcomes["history_without_session"] += 1
    broken = outcomes["alive_without_history"] + outcomes["history_without_session"]
    return {**outcomes, "trials": TRIALS, "inconsistent": broken, "inconsistent_rate": round(broken / TRIALS, 4)}


def write(label: str, result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {})[label] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="results.json 의 session_race 아래 키(코드 시점)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    result = asyncio.run(measure())
    print(json.dumps(result, ensure_ascii=False))
    if not args.dry_run:
        write(args.label, result)


if __name__ == "__main__":
    main()
