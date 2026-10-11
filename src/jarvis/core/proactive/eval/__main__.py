"""[core] proactive 평가 CLI: python -m jarvis.core.proactive.eval [--suite S] [--engine none|llm] [--json] [-v]."""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from jarvis.core.proactive.eval.runner import SUITES, format_report, load_suites, run_cases

if TYPE_CHECKING:
    from jarvis.agent_layer.thought import InnerThoughtEngine

# 엔진 프롬프트의 [지금] 값. 고정해야 같은 상황이 같은 프롬프트가 된다
FIXED_CLOCK = datetime(2026, 1, 1, 9, 0, 0)


def _llm_engine() -> "InnerThoughtEngine":
    from jarvis.agent_layer.thought import InnerThoughtEngine, ThoughtPromptTemplate
    from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE
    from jarvis.config import get_settings
    from jarvis.model_layer.types import ModelConfig

    settings = get_settings()
    llm, tcfg = settings.llm, settings.thought
    secret = tcfg.api_key or llm.api_key
    api_key = secret.get_secret_value() if secret else None
    model = ModelConfig(
        provider=tcfg.provider or llm.provider,
        model=tcfg.model or llm.model,
        api_key=api_key,
        base_url=tcfg.base_url or llm.base_url,
    )
    return InnerThoughtEngine(
        model=model,
        template=ThoughtPromptTemplate.load(tcfg.prompt_path),
        reflection_template=ThoughtPromptTemplate.load(
            tcfg.reflection_prompt_path, default=DEFAULT_REFLECTION_TEMPLATE
        ),
        clock=lambda: FIXED_CLOCK,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis.core.proactive.eval")
    parser.add_argument("--suite", default="all", choices=("all", *SUITES))
    parser.add_argument("--engine", default="none", choices=("none", "llm"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    # engine 이 none 이면 frame 이 있는 사례만 판정하고 상황 사례는 건너뛴다(LLM 없이 정책 회귀 검사).
    names = list(SUITES) if args.suite == "all" else [args.suite]
    engine = _llm_engine() if args.engine == "llm" else None
    report = asyncio.run(run_cases(load_suites(names), engine))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report, args.verbose))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
