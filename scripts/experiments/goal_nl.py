"""[scripts] KAREN 에게 계속 챙길 말과 한 번 찾을 말을 보내 첫 도구 호출이 goal 인지 재고, 회상 기억의 영향을 견준다."""

# 백엔드 컨테이너에서: python -m scripts.experiments.goal_nl --repeat 3 [--memory live|clean|none]
# 도구는 실행하지 않는다. 첫 응답의 도구 이름만 본다.
# live 는 지금 장기 기억에서 이 말로 떠오르는 항목과 작업 패턴을 넣고, clean 은 그중 테스트 세션 항목을 뺀다

import json
import asyncio
import argparse
from pathlib import Path

from jarvis.memory.memory_service import LTM_HEADER, RECALL_KINDS, MemoryService, _block
from jarvis.model_layer.types import LLMContext, Message, ModelConfig, Tool, UserMessage
from jarvis.core.tools.task_pattern import TOOL_DESCRIPTION as PATTERN_DESCRIPTION
from jarvis.core.tools.task_pattern import TOOL_PARAMETERS as PATTERN_PARAMETERS
from jarvis.core.scheduler.tool import TOOL_DESCRIPTION as SCHEDULE_DESCRIPTION
from jarvis.core.scheduler.tool import TOOL_PARAMETERS as SCHEDULE_PARAMETERS
from jarvis.memory.long_term.task_pattern import best_matches, render_block
from jarvis.agent_layer.session.protocol import TEST_SESSION_PREFIXES
from jarvis.core.goals.tool import TOOL_DESCRIPTION, TOOL_PARAMETERS
from jarvis.core.tools.housing import ProfileStore, housing_tools
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.stores.postgres import PostgresItemStore
from jarvis.app.agent_profile import compose_system_prompt
from jarvis.model_layer.stream import stream_to_message
from jarvis.app.agent_registry import load_agent_specs
from jarvis.app.infra_builder import InfraBuilder
from jarvis.memory.scope import MemoryScope
from jarvis.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts" / "experiments" / "results.json"
RESULT_KEY = "goal_nl"
# 계속 챙길 말(goal 이어야 한다)과 지금 한 번 찾을 말(goal 이 아니어야 한다)
KEEP = [
    "조건 및 가장 좋은 원리금 납부액을 추천하는 공고만 알려줘",
    "서울에 새 행복주택 공고 나오면 알려줘",
    "월 부담 100만원 안쪽 공고 생기면 알려줘",
    "앞으로 추천 1순위 바뀌면 알려줘",
]
ONCE = [
    "지금 올라온 공고 중 서울 것만 알려줘",
    "현금 1억, 월 150으로 맞는 공고 찾아줘",
    "가장 추천하는 게 뭐야?",
    "동탄 행복주택 마감일만 알려줘",
]


def tools() -> list[Tool]:
    store = ProfileStore(MemoryService(InMemoryItemStore()))
    found = [Tool(name=t.name, description=t.description, parameters=t.parameters) for t in housing_tools(store)]
    return found + [
        Tool(name="goal", description=TOOL_DESCRIPTION, parameters=TOOL_PARAMETERS),
        Tool(name="schedule", description=SCHEDULE_DESCRIPTION, parameters=SCHEDULE_PARAMETERS),
        Tool(name="remember_task_pattern", description=PATTERN_DESCRIPTION, parameters=PATTERN_PARAMETERS),
    ]


async def recalled(memory: MemoryService | None, text: str, scope: MemoryScope, clean: bool) -> list[Message]:
    """세션이 첫 턴에 붙이는 회상 블록과 작업 패턴 블록. 기억을 쓰지 않으면 빈 목록."""
    if memory is None:
        return []
    items = await memory.recall(text, scope, kinds=RECALL_KINDS, limit=3 + 10)
    if clean:
        items = [i for i in items if not (i.scope.session_id or "").startswith(TEST_SESSION_PREFIXES)]
    blocks: list[Message] = [_block(LTM_HEADER, items[:3])] if items else []
    patterns = best_matches(await memory.task_patterns(scope), text, 2)
    if patterns:
        blocks.append(UserMessage(content=render_block(patterns)))
    return blocks


async def run(repeat: int, mode: str) -> dict[str, object]:
    settings = get_settings()
    spec = load_agent_specs(str(ROOT / "team"))["karen"]
    key = settings.llm.api_key.get_secret_value() if settings.llm.api_key else None
    model = ModelConfig(provider=settings.llm.provider, model=spec.model or settings.llm.model, api_key=key,
                        base_url=settings.llm.base_url, timeout=120.0)
    memory = None
    if mode != "none":
        embedder = InfraBuilder(settings).build_embedder()
        dsn = settings.memory.postgres_dsn or settings.session.postgres_dsn
        store = PostgresItemStore(dsn=dsn, dimensions=embedder.dimensions if embedder else 0)
        memory = MemoryService(store, embedder=embedder)
    scope = MemoryScope(user_id="local", agent_id="karen")
    system = compose_system_prompt(spec.persona, spec.system_prompt)
    rows = []
    for text, want_goal in [(t, True) for t in KEEP] + [(t, False) for t in ONCE]:
        blocks = await recalled(memory, text, scope, mode == "clean")
        for _ in range(repeat):
            ctx = LLMContext(messages=[*blocks, UserMessage(content=text)], tools=tools(), system_prompt=system)
            msg = await stream_to_message(model, ctx)
            calls = [c.name for c in msg.tool_calls()]
            ok = ("goal" in calls) == want_goal
            rows.append({"text": text, "want_goal": want_goal, "calls": calls, "ok": ok})
            print("OK " if ok else "BAD", text[:30], calls)
    keep = [r for r in rows if r["want_goal"]]
    once = [r for r in rows if not r["want_goal"]]
    return {
        "mode": mode,
        "model": model.model,
        "repeat": repeat,
        "keep_goal": f"{sum(r['ok'] for r in keep)}/{len(keep)}",
        "once_not_goal": f"{sum(r['ok'] for r in once)}/{len(once)}",
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--memory", choices=("live", "clean", "none"), default="live")
    args = parser.parse_args()
    result = asyncio.run(run(args.repeat, args.memory))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    saved[f"{RESULT_KEY}_{args.memory}"] = {k: v for k, v in result.items() if k != "rows"}
    OUT.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
