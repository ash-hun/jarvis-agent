"""[scripts] 알림이 확률 p 로 실패할 때 housing_watch 스케줄이 끝내 못 전하는 새 공고 수를 세어 results.json 에 쓴다."""

import os
import sys
import json
import random
import asyncio
import argparse
import tempfile
from typing import Any
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JARVIS_LLM__PROVIDER", "faux")
os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from jarvis.core.scheduler.scheduler_service import SchedulerService, TaskAgent
from jarvis.core.tools.housing.watch import HousingWatchTool, SeenStore
from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.core.tools.housing.lh_notice import Notice
from jarvis.model_layer.model_types import ModelConfig
from jarvis.core.scheduler.task import ScheduledTask
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "housing_delivery"
DAYS = 60  # 새 공고가 올라오는 날 수. 매일 한 번 도는 스케줄(0 9 * * *)
OPEN_DAYS = 14  # 공고가 올라온 뒤 마감까지. 마지막 공고도 마감까지 스케줄이 더 돈다
NEW_PER_DAY = (0, 1, 2)  # 하루에 새로 올라오는 공고 수(균등)
SEEDS = 20
FAIL_RATES = (0.0, 0.1, 0.3)
START = date(2026, 10, 13)
PROFILE = HousingProfile(married=False, income=36_000_000)


class Board:
    """LH 목록 대역. 올라온 공고는 마감까지 목록에 남는다(실제 공고중 목록처럼)."""

    def __init__(self) -> None:
        self.notices: list[Notice] = []

    def post(self, today: date) -> str:
        seq = len(self.notices)
        closes = today + timedelta(days=OPEN_DAYS)
        self.notices.append(Notice(
            f"2015122300{seq:06d}-03-06-10", "국민임대", f"공고{seq:04d} 국민임대", "강원특별자치도",
            today.strftime("%Y.%m.%d"), closes.strftime("%Y.%m.%d"), "공고중",
        ))
        return f"공고{seq:04d}"

    async def search(self, queries: Any, today: date) -> list[tuple[str, int, list[Notice]]]:
        return [("임대", len(self.notices), list(self.notices))]


class Profiles:
    async def get(self, user_id: str) -> HousingProfile:
        return PROFILE


async def simulate(fail_rate: float, seed: int, root: str) -> dict[str, int]:
    # 공고와 알림 실패는 따로 뽑는다. 실패율과 코드 시점이 달라도 올라오는 공고는 같다
    posting, failing = random.Random(seed), random.Random(seed + 1_000_003)
    board = Board()
    today = [START]
    tool = HousingWatchTool(board, SeenStore(f"{root}/{fail_rate}-{seed}"), lambda: today[0], Profiles())  # type: ignore[arg-type]
    tools = ToolRegistry()
    tools.register(tool)
    svc = SchedulerService(
        tasks=[], session_repo=MagicMock(create=AsyncMock()), tool_registry=ToolRegistry(),
        model=ModelConfig(provider="faux", model="faux-model"),
    )
    svc.set_agent_resolver(lambda a: TaskAgent(MagicMock(), None, "karen", tools) if a == "karen" else None)
    delivered_texts: list[str] = []
    failures = 0

    async def notify(payload: dict[str, Any]) -> None:
        nonlocal failures
        if failing.random() < fail_rate:
            failures += 1
            raise RuntimeError("push 실패")
        delivered_texts.append(str(payload["text"]))

    svc.set_notifier(notify)
    task = ScheduledTask(name="watch", schedule="0 9 * * *", prompt="", kind="tool", tool="housing_watch",
                         args={"regions": "강원", "quiet": True}, agent="karen")
    posted: list[str] = []
    for day in range(DAYS + OPEN_DAYS):
        for _ in range(posting.choice(NEW_PER_DAY) if day < DAYS else 0):
            posted.append(board.post(today[0]))
        svc.run_soon(task)
        await asyncio.gather(*(asyncio.all_tasks() - {asyncio.current_task()}))
        today[0] += timedelta(days=1)
    counts = {name: sum(name in text for text in delivered_texts) for name in posted}
    return {
        "posted": len(posted),
        "never_delivered": sum(1 for n in counts.values() if n == 0),
        "delivered_twice": sum(1 for n in counts.values() if n > 1),
        "notify_failures": failures,
        "notifications": len(delivered_texts),
    }


async def measure() -> dict[str, Any]:
    rows = []
    with tempfile.TemporaryDirectory() as root:
        for rate in FAIL_RATES:
            runs = [await simulate(rate, seed, root) for seed in range(SEEDS)]
            posted = sum(r["posted"] for r in runs)
            missed = sum(r["never_delivered"] for r in runs)
            rows.append({
                "fail_rate": rate,
                "posted": posted,
                "never_delivered": missed,
                "miss_rate": round(missed / posted, 3),
                "delivered_twice": sum(r["delivered_twice"] for r in runs),
                "notify_failures": sum(r["notify_failures"] for r in runs),
                "notifications": sum(r["notifications"] for r in runs),
            })
    return {"rows": rows, "seeds": SEEDS, "days": DAYS, "open_days": OPEN_DAYS}


def write(label: str, result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {})[label] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="results.json 의 housing_delivery 아래 키(코드 시점)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    result = asyncio.run(measure())
    print(json.dumps(result, ensure_ascii=False))
    if not args.dry_run:
        write(args.label, result)


if __name__ == "__main__":
    main()
