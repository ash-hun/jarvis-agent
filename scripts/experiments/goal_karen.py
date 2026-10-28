"""[scripts] KAREN 의 추천 공고 목표를 실제 LH 게시판과 모델로 여러 차례 돌려 맞음, 중복, 시간, 비용을 잰다."""

# 백엔드 컨테이너 안에서: python -m scripts.experiments.goal_karen --runs 3
# 사용자의 실제 프로필과 목표는 건드리지 않는다.
# 가정한 돈 조건을 메모리 안 프로필에 두고, 목표와 세션은 임시 디렉터리에 둔다

import re
import json
import time
import asyncio
import argparse
import tempfile
from pathlib import Path
from datetime import date

from jarvis.core.tools.housing.profile import HousingProfile, ProfileStore
from jarvis.model_layer.types import AssistantMessage, ToolResultMessage
from jarvis.core.scheduler.service import SchedulerService, TaskAgent
from jarvis.core.goals.types import parse_step, Goal, goal_key
from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.app.agent_profile import compose_system_prompt
from jarvis.app.agent_registry import load_agent_specs
from jarvis.memory.memory_service import MemoryService
from jarvis.core.tools.housing.fetch import kst_today
from jarvis.core.scheduler.task import ScheduledTask
from jarvis.core.tools.housing import housing_tools
from jarvis.core.tools.registry import ToolRegistry
from jarvis.core.goals.runner import GoalRunner
from jarvis.core.goals.store import GoalStore
from jarvis.core.goals.tool import goal_task
from jarvis.memory.scope import MemoryScope
from jarvis.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts" / "experiments" / "results.json"
RESULT_KEY = "goal_karen"
GOAL = "조건 및 가장 좋은 원리금 납부액을 추천하는 공고만 알려줘"
# 가정한 조건. 사용자 실제 값이 아니다(사용자 프로필은 비어 있다)
ASSUMED = {"cash": 150_000_000, "monthly_limit": 2_000_000, "regions": ("서울", "경기")}
NOTICE_ID = re.compile(r"panId=([0-9A-Za-z]+)")


async def ground_truth(tools: ToolRegistry, scope: MemoryScope) -> tuple[list[str], list[str], list[str], float]:
    """도구를 직접 불러 얻은 추천 1순위 줄, 그 공고 panId, 항목 키. 모델이 고른 것과 견줄 정답이다."""
    from jarvis.core.tools.registry import ToolContext

    started = time.perf_counter()
    params = {"picks_only": True}
    result = await tools.execute("truth", "housing_budget", params, None, ToolContext(scope=scope, session_id="truth"))
    took = time.perf_counter() - started
    text = result.content[0].text  # type: ignore[union-attr]
    lines = [line for line in text.splitlines() if line.startswith("추천 1순위(") and "없음" not in line]
    ids = [m.group(1) for line in lines for m in NOTICE_ID.finditer(line)]
    keys = [m.group(1) for line in lines for m in re.finditer(r"항목: \[([^\]]+)\]", line)]
    return lines, ids, keys, took


async def run(runs: int, with_money: bool, seed_first: bool = False) -> dict[str, object]:
    settings = get_settings()
    spec = load_agent_specs(str(ROOT / "team"))["karen"]
    key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else None
    from jarvis.model_layer.types import ModelConfig

    model = ModelConfig(provider=settings.llm.provider, model=spec.model or settings.llm.model, api_key=key,
                        base_url=settings.llm.base_url, timeout=120.0)
    memory = MemoryService(InMemoryItemStore())
    profiles = ProfileStore(memory)
    scope = MemoryScope(user_id="local", agent_id="karen")
    profile = HousingProfile(**ASSUMED) if with_money else HousingProfile(regions=ASSUMED["regions"])
    await profiles.save(profile, scope, date.today())
    tools = ToolRegistry()
    for tool in housing_tools(profiles=profiles):
        if tool.name in spec.tools:
            tools.register(tool)
    truth: tuple[list[str], list[str], list[str], float] = ([], [], [], 0.0)
    if with_money:
        truth = await ground_truth(tools, scope)
    truth_lines, truth_ids, truth_keys, truth_sec = truth

    with tempfile.TemporaryDirectory() as root:
        store = GoalStore(f"{root}/goals")
        repo = JsonlSessionRepo(f"{root}/sessions")
        svc = SchedulerService(tasks=[], session_repo=repo, tool_registry=ToolRegistry(), model=model)
        prompt = compose_system_prompt(spec.persona, spec.system_prompt)
        svc.set_agent_resolver(lambda a: TaskAgent(model, prompt, "karen", tools, tuple(spec.boundaries.ask)))
        runner = GoalRunner(store)
        svc.set_goal_runner(runner)
        spoken: list[str] = []

        async def converse(agent: str, text: str) -> bool:
            spoken.append(text)
            return True

        svc.set_conversation(converse)
        created: list[str] = []
        create = repo.create

        async def recording_create(session_id, **kw):  # type: ignore[no-untyped-def]
            created.append(session_id)
            return await create(session_id=session_id, **kw)

        repo.create = recording_create  # type: ignore[method-assign]
        replies: list[str | None] = []
        execute = svc._execute_task

        async def recording(task, pick=None):  # type: ignore[no-untyped-def]
            reply = await execute(task, pick)
            replies.append(reply)
            return reply

        svc._execute_task = recording  # type: ignore[method-assign]
        goal, _ = store.ensure(Goal(id=goal_key("karen", GOAL), agent="karen", text=GOAL))
        if seed_first and truth_ids:
            # 1순위 하나는 이미 알렸다고 둔다. 바뀐 것(나머지)만 알려야 한다
            goal = goal.model_copy(update={"reported": [truth_keys[0]]})
            store.save(goal)
        task: ScheduledTask = goal_task(goal)
        rows = []
        for i in range(runs):
            before = len(spoken)
            started = time.perf_counter()
            await svc._run_and_deliver(task)
            took = time.perf_counter() - started
            messages = await repo.get_messages(created[-1]) if created else []
            answers = [m for m in messages if isinstance(m, AssistantMessage)]
            reply = replies[-1] or ""
            step = parse_step(reply)
            said = spoken[before:]
            mentioned = [m.group(1) for text in said for m in NOTICE_ID.finditer(text)]
            rows.append({
                "run": i + 1,
                "took_sec": round(took, 1),
                "parsed": step.parsed,
                "reported": bool(said),
                "keys": [k for k, _ in step.items],
                "keyless": step.keyless,
                "mentioned_ids": mentioned,
                # 알린 공고가 모두 정답(추천 1순위) 안에 있는가
                "only_top": all(m in truth_ids for m in mentioned),
                "tools": [c.name for m in answers for c in m.tool_calls()],
                "args": [c.arguments for m in answers for c in m.tool_calls()],
                "results": [m.content[0].text[:160] for m in messages
                            if isinstance(m, ToolResultMessage) and m.content],
                "tokens_in": sum(m.usage.input for m in answers),
                "tokens_out": sum(m.usage.output for m in answers),
                "said": said,
                "reply": reply,
            })
            print(json.dumps(rows[-1], ensure_ascii=False))
        saved_goal = store.get(goal.id)
    first_reported = [r for r in rows if r["reported"]]
    return {
        "with_money": with_money,
        "assumed": {k: list(v) if isinstance(v, tuple) else v for k, v in ASSUMED.items()},
        "date": kst_today().isoformat(),
        "model": model.model,
        "truth_lines": truth_lines,
        "truth_ids": truth_ids,
        "truth_keys": truth_keys,
        # 알린 줄의 링크가 정답 링크와 글자 하나 다르지 않은가(모델이 줄이던 것)
        "links_exact": all(
            any(url in t for t in truth_lines)
            for r in rows for said in r["said"] for url in re.findall(r"https://\S+?(?=\s|$)", said)
        ),
        "truth_tool_sec": round(truth_sec, 1),
        "runs": runs,
        "parsed": sum(bool(r["parsed"]) for r in rows),
        "reports": len(first_reported),
        # 첫 보고가 정답 공고를 모두 담았는가
        "recall": (sorted(set(first_reported[0]["mentioned_ids"])) == sorted(set(truth_ids[seed_first:])))  # type: ignore[arg-type]
        if first_reported and truth_ids else None,
        "only_top": all(bool(r["only_top"]) for r in rows),
        "seed_first": seed_first,
        # 이미 알렸다고 둔 공고를 다시 알렸는가
        "repeated_seeded": any(truth_ids[0] in r["mentioned_ids"] for r in rows) if seed_first and truth_ids else None,
        "repeat_reports": max(0, len(first_reported) - 1),
        "took_sec": [r["took_sec"] for r in rows],
        "tokens_in": [r["tokens_in"] for r in rows],
        "tokens_out": [r["tokens_out"] for r in rows],
        "reported_keys": saved_goal.reported if saved_goal else [],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--no-money", action="store_true", help="현금을 모르는 경우(묻기만 해야 한다)")
    parser.add_argument("--seed-first", action="store_true", help="1순위 하나는 이미 알렸다고 두고 시작")
    args = parser.parse_args()
    result = asyncio.run(run(args.runs, not args.no_money, args.seed_first))
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    name = RESULT_KEY + ("_no_money" if args.no_money else "") + ("_seed_first" if args.seed_first else "")
    saved[name] = {k: v for k, v in result.items() if k != "rows"}
    OUT.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
