"""[scripts] τ²-bench airline, retail 과제를 운영 에이전트 루프와 사용자 시뮬레이터로 돌려 공식 보상으로 채점한다."""

# 출처: sierra-research/tau2-bench v2.0.0 (MIT License, Copyright (c) 2025 Sierra Research).
# 에이전트 지시문은 src/tau2/agent/llm_agent.py, 사용자 시뮬레이터 지시문은 src/tau2/user/guidelines.py 의
# _TEXT_PLAIN 과 user_simulator.py 의 SYSTEM_PROMPT, 첫 인사와 종료 규칙(max_steps 200, max_errors 10)은
# src/tau2/config.py 와 orchestrator/orchestrator.py 에서 옮겼다

import sys
import json
import random
import asyncio
import hashlib
import argparse
import textwrap
import contextvars
from typing import Any
from pathlib import Path
from collections.abc import AsyncIterator
from scripts.experiments.models import model_config
from scripts.experiments.tau2_score import pass_hat_1, score_episode
from scripts.experiments.tau2_tools import DOMAIN_DIR, ROOT, SCHEMAS, TOOLKITS, OverlayDB, load_base

from jarvis.model_layer.model_types import (
    AssistantMessage,
    LLMContext,
    Message,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextContent,
    Tool,
    ToolResultMessage,
    UserMessage,
)
from jarvis.agent_layer.agent_types import AgentContext, AgentEvent, AgentLoopConfig, TurnStartEvent
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.model_layer.providers.provider_base import Provider
from jarvis.model_layer.stream import stream_to_message
from jarvis.agent_layer.loop import run_agent_loop

CACHE = ROOT / "cache"
DOMAINS = ("airline", "retail")
PER_DOMAIN = 20
VERSION = "tau2-v1"  # 실행 규칙이나 프롬프트를 바꾸면 올려 예전 캐시를 읽지 않게 한다
MAX_STEPS = 200
MAX_ERRORS = 10
TASK_TIMEOUT_SEC = 1_800
FIRST_AGENT_MESSAGE = "Hi! How can I help you today?"
STOP_TOKENS = ("###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###")
AGENT_INSTRUCTION = (
    "You are a customer service agent that helps the user according to the <policy> provided below.\n"
    "In each turn you can either:\n- Send a message to the user.\n- Make a tool call.\n"
    "You cannot do both at the same time.\n\n"
    "Try to be helpful and always follow the policy. Always make sure you generate valid JSON only."
)
USER_GUIDELINES = """# User Simulation Guidelines
You are playing the role of a customer contacting a customer service representative.
Your goal is to simulate realistic customer interactions while following specific scenario instructions.

## Core Principles
- Generate one message at a time, maintaining natural conversation flow.
- Strictly follow the scenario instructions you have received.
- When providing addresses or other multi-part entity values from the task, preserve the order of their components exactly as given; do not rearrange them to match local conventions unless the task explicitly instructs a different order.
- Never make up or hallucinate information not provided in the scenario instructions. Information that is not provided in the scenario instructions should be considered unknown or unavailable.
- Avoid repeating the exact instructions verbatim. Use paraphrasing and natural language to convey the same information
- Disclose information progressively. Wait for the agent to ask for specific information before providing it.

## Persona Guidelines


## Task Completion
- The goal is to continue the conversation until the task is complete.
- If the instruction goal is satisified, generate the '###STOP###' token to end the conversation.
- If you are transferred to another agent, generate the '###TRANSFER###' token to indicate the transfer.
- If you find yourself in a situation in which the scenario does not provide enough information for you to continue the conversation, generate the '###OUT-OF-SCOPE###' token to end the conversation.
Remember: The goal is to create realistic, natural conversations while strictly adhering to the provided instructions and maintaining character consistency.
"""  # noqa: E501, W291 - 원본 문구를 줄바꿈과 끝 공백까지 그대로 둔다

_meter: contextvars.ContextVar[dict[str, dict[str, int]]] = contextvars.ContextVar("tau2_meter")
_role: contextvars.ContextVar[str] = contextvars.ContextVar("tau2_role", default="agent")
_bases: dict[str, dict[str, dict[str, Any]]] = {}


# ── 과제와 표본: 모델과 무관한 순수 함수 ──

def load_tasks(domain: str) -> dict[str, dict[str, Any]]:
    """공식 test split 의 과제만. split_tasks.json 의 test 가 평가용으로 떼어 둔 목록이다."""
    folder = DOMAIN_DIR / domain
    test = set(json.loads((folder / "split_tasks.json").read_text("utf-8"))["test"])
    return {t["id"]: t for t in json.loads((folder / "tasks.json").read_text("utf-8")) if t["id"] in test}


def pick_tasks(ids_by_domain: dict[str, list[str]], per_domain: int, seed: int,
               limit: int | None = None) -> list[tuple[str, str]]:
    """도메인마다 id 순으로 정렬한 test 과제에서 seed 로 per_domain 개를 고르고, 도메인을 번갈아 늘어놓는다."""
    picked = {d: random.Random(seed).sample(sorted(ids, key=int), min(per_domain, len(ids)))
              for d, ids in sorted(ids_by_domain.items())}
    order = [(d, picked[d][i]) for i in range(max(map(len, picked.values()), default=0))
             for d in sorted(picked) if i < len(picked[d])]
    return order if limit is None else order[:limit]


def user_instructions(scenario: dict[str, Any]) -> str:
    """원본 UserScenario.__str__ 와 StructuredUserInstructions.__str__ 의 글 모양."""
    lines = []
    if scenario.get("persona") is not None:
        lines += ["Persona:", textwrap.indent(scenario["persona"], "\t")]
    inst = scenario["instructions"]
    if isinstance(inst, dict):
        body = [f"Domain: {inst['domain']}", f"Reason for call:\n{textwrap.indent(inst['reason_for_call'], chr(9))}"]
        if inst.get("known_info") is not None:
            body.append(f"Known info:\n{textwrap.indent(inst['known_info'], chr(9))}")
        if inst.get("unknown_info") is not None:
            body.append(f"Unknown info:\n{textwrap.indent(inst['unknown_info'], chr(9))}")
        body.append(f"Task instructions:\n{textwrap.indent(inst['task_instructions'], chr(9))}")
        text = "\n".join(body)
    else:
        text = str(inst)
    lines += ["Instructions:", textwrap.indent(text, "\t")]
    return "\n".join(lines)


def user_system_prompt(scenario: dict[str, Any]) -> str:
    return f"{USER_GUIDELINES}\n\n<scenario>\n{user_instructions(scenario)}\n</scenario>".strip()


def agent_system_prompt(policy: str) -> str:
    return f"<instructions>\n{AGENT_INSTRUCTION}\n</instructions>\n<policy>\n{policy}\n</policy>"


def count_steps(messages: list[Message]) -> int:
    """공식 orchestrator 의 한 단계: 에이전트 메시지 하나, 도구 결과 묶음 하나, 사용자 메시지 하나."""
    steps = 0
    for m in messages:
        if isinstance(m, AssistantMessage):
            steps += 1 + bool(m.tool_calls())
        elif isinstance(m, UserMessage):
            steps += 1
    return steps


def gold_changes(domain: str, base: dict[str, dict[str, Any]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    """정답 행동을 초기 DB 에 차례로 적용한 결과. 공식처럼 실패한 행동은 건너뛴다."""
    db = OverlayDB(base)
    tools = TOOLKITS[domain](db)
    for action in actions:
        tools.call(action["name"], action["arguments"])
    return db.changes()


def base_db(domain: str) -> dict[str, dict[str, Any]]:
    if domain not in _bases:
        _bases[domain] = load_base(domain)
    return _bases[domain]


# ── LLM 호출 계량: 메인 모델(agent)과 사용자 시뮬레이터(user)를 나눠 센다 ──

class MeteredProvider(Provider):
    """실제 provider 를 감싸 호출 수와 입력, 출력 토큰을 역할별로 더한다."""

    def __init__(self, inner: str) -> None:
        self.provider_name = f"tau2-{inner}"
        self._inner = get_default_registry().get(inner)

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        slot = _meter.get().setdefault(_role.get(), {"calls": 0, "input": 0, "output": 0, "cache_read": 0})
        slot["calls"] += 1
        async for event in self._inner.stream(model, context, options):
            if isinstance(event, StopEvent):
                slot["input"] += event.usage.input
                slot["output"] += event.usage.output
                slot["cache_read"] += event.usage.cache_read
            yield event


def metered(model: str) -> ModelConfig:
    cfg = model_config(model).model_copy(update={"temperature": 0.0})
    if f"tau2-{cfg.provider}" not in get_default_registry().list_names():
        get_default_registry().register(MeteredProvider(cfg.provider))
    return cfg.model_copy(update={"provider": f"tau2-{cfg.provider}"})


# ── 과제 하나: 사용자 시뮬레이터와 에이전트 루프가 번갈아 말한다 ──

def cache_path(model: str, judge_model: str, domain: str, task_id: str) -> Path:
    prompt = agent_system_prompt((DOMAIN_DIR / domain / "policy.md").read_text("utf-8"))
    setting = f"{VERSION}|{model}|{judge_model}|{domain}|{task_id}|{MAX_STEPS}|{MAX_ERRORS}|{prompt}|{USER_GUIDELINES}"
    key = hashlib.sha1((setting + json.dumps(SCHEMAS[domain], sort_keys=True)).encode()).hexdigest()[:16]
    return CACHE / f"{domain}_{task_id}_{key}.json"


def _clip(text: str, n: int = 400) -> str:
    return text if len(text) <= n else text[:n] + f"...({len(text)}자)"


async def run_task(domain: str, task: dict[str, Any], model: str, judge_model: str) -> dict[str, Any]:
    cached = cache_path(model, judge_model, domain, task["id"])
    if cached.exists():
        hit: dict[str, Any] = json.loads(cached.read_text("utf-8"))
        return {**hit, "cached": True}
    _meter.set({})
    policy = (DOMAIN_DIR / domain / "policy.md").read_text("utf-8")
    db = OverlayDB(base_db(domain))
    tools = TOOLKITS[domain](db)
    signal = asyncio.Event()
    state: dict[str, Any] = {"errors": 0, "steps": 1, "termination": ""}
    transcript: list[dict[str, Any]] = [{"role": "agent", "text": FIRST_AGENT_MESSAGE}]

    async def execute(call_id: str, name: str, args: dict[str, Any]) -> ToolResultMessage:
        text, failed = tools.call(name, args)
        state["errors"] += failed
        transcript.append({"role": "tool", "name": name, "args": args, "error": failed, "result": _clip(text)})
        if state["errors"] >= MAX_ERRORS:
            state["termination"] = "too_many_errors"
            signal.set()
        return ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[TextContent(text=text)],
                                 is_error=failed)

    context = AgentContext(
        session_id=f"tau2-{domain}-{task['id']}",
        messages=[AssistantMessage(content=[TextContent(text=FIRST_AGENT_MESSAGE)])],
        tools=[Tool(**schema) for schema in SCHEMAS[domain]], model=metered(model),
        system_prompt=agent_system_prompt(policy),
    )
    turn_start = 0

    async def emit(event: AgentEvent) -> None:
        # 공식처럼 단계마다 상한을 본다. 에이전트가 도구만 부르며 돌아도 200 단계에서 끊긴다
        live = state["steps"] + count_steps(context.messages[turn_start:])
        if isinstance(event, TurnStartEvent) and live >= MAX_STEPS:
            state["termination"] = state["termination"] or "max_steps"
            signal.set()

    simulator = metered(judge_model)
    sim_system = user_system_prompt(task["user_scenario"])
    sim_history: list[Message] = [UserMessage(content=FIRST_AGENT_MESSAGE)]
    error: str | None = None
    while not state["termination"]:
        _role.set("user")
        reply = await stream_to_message(simulator, LLMContext(messages=sim_history, system_prompt=sim_system))
        if reply.error_message is not None:
            error = f"user simulator: {reply.error_message}"
            break
        said = reply.text()
        sim_history.append(AssistantMessage(content=[TextContent(text=said)]))
        transcript.append({"role": "user", "text": said})
        state["steps"] += 1
        if any(token in said for token in STOP_TOKENS):
            state["termination"] = "user_stop"
            break
        if state["steps"] >= MAX_STEPS:
            state["termination"] = "max_steps"
            break
        _role.set("agent")
        context.messages.append(UserMessage(content=said))
        turn_start = len(context.messages)
        final = await run_agent_loop(context, AgentLoopConfig(), emit, execute, signal=signal)
        state["steps"] += count_steps(context.messages[turn_start:])
        if state["termination"]:
            break
        if final is None or final.error_message is not None:
            error = f"agent: {final.error_message if final else 'no reply'}"
            break
        answer = final.text()
        transcript.append({"role": "agent", "text": answer})
        sim_history.append(UserMessage(content=answer))
        if state["steps"] >= MAX_STEPS:
            state["termination"] = "max_steps"
    if error is not None:
        raise RuntimeError(error)

    agent_texts = [m.text() for m in context.messages if isinstance(m, AssistantMessage) and m.text()]
    result = score_episode(
        termination=state["termination"], predicted_changes=db.changes(),
        gold_changes=gold_changes(domain, base_db(domain), task["evaluation_criteria"].get("actions") or []),
        criteria=task["evaluation_criteria"], agent_texts=agent_texts,
    )
    meter = _meter.get()
    row = {
        "domain": domain, "id": task["id"], **result, "termination": state["termination"],
        "steps": state["steps"], "tool_errors": state["errors"],
        "agent": meter.get("agent", {}), "user": meter.get("user", {}), "transcript": transcript,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**row, "cached": False}


# ── 묶기 ──

def _mean(rows: list[dict[str, Any]], role: str, key: str) -> float:
    return round(sum(r[role].get(key, 0) for r in rows) / len(rows), 1) if rows else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """도메인별 pass^1 과 문항당 평균 LLM 호출 수, 토큰(메인 모델과 시뮬레이터 따로)."""
    detail: dict[str, Any] = {}
    for domain in DOMAINS:
        part = [r for r in rows if r["domain"] == domain]
        if part:
            detail[domain] = {"pass^1": round(pass_hat_1([r["reward"] for r in part]), 3), "n": len(part)}
    detail["per_task"] = {role: {k: _mean(rows, role, k) for k in ("calls", "input", "output")}
                          for role in ("agent", "user")}
    detail["terminations"] = {t: sum(r["termination"] == t for r in rows) for t in sorted({r["termination"]
                                                                                           for r in rows})}
    return detail


async def run_vertex(model: str, *, judge_model: str = "gpt-4o", limit: int | None = None, seed: int = 0,
                     concurrency: int = 4) -> dict[str, Any]:
    """스코어카드 계약. 도메인마다 seed 로 고른 20 과제, score = pass^1 × 100. 실패 문항은 0 점과 errors 로 센다."""
    tasks = {d: load_tasks(d) for d in DOMAINS}
    picked = pick_tasks({d: list(t) for d, t in tasks.items()}, PER_DOMAIN, seed, limit)
    gate = asyncio.Semaphore(concurrency)

    async def one(domain: str, task_id: str) -> dict[str, Any] | None:
        async with gate:
            try:
                return await asyncio.wait_for(run_task(domain, tasks[domain][task_id], model, judge_model),
                                              TASK_TIMEOUT_SEC)
            except Exception as exc:  # noqa: BLE001 - 문항 하나의 실패로 전체를 멈추지 않는다
                print(f"[tau2] {domain}/{task_id} 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
                return None

    outcomes = await asyncio.gather(*(one(d, i) for d, i in picked))
    rows = [r for r in outcomes if r is not None]
    errors = len(outcomes) - len(rows)
    rewards = [r["reward"] for r in rows] + [0.0] * errors
    raw = pass_hat_1(rewards)
    detail = summarize(rows) if rows else {}
    for domain in DOMAINS:
        failed = sum(o is None for (d, _), o in zip(picked, outcomes, strict=True) if d == domain)
        if domain in detail and failed:
            part = [r["reward"] for r in rows if r["domain"] == domain] + [0.0] * failed
            detail[domain] = {"pass^1": round(pass_hat_1(part), 3), "n": len(part)}
    detail["tasks"] = [{"domain": r["domain"], "id": r["id"], "reward": r["reward"], "db_match": r["db_match"],
                        "termination": r["termination"], "cached": r["cached"],
                        "agent": r["agent"], "user": r["user"]} for r in rows]
    return {"score": round(raw * 100, 2), "n": len(outcomes), "raw": raw, "detail": detail, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not (DOMAIN_DIR / "airline" / "tasks.json").exists():
        sys.exit(f"τ²-bench 데이터가 없다: {DOMAIN_DIR} (docs/features.md 의 재현 절차로 받는다)")
    result = asyncio.run(run_vertex(args.model, judge_model=args.judge_model, limit=args.limit, seed=args.seed,
                                    concurrency=args.concurrency))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
