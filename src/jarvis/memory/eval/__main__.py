"""python -m jarvis.memory.eval --suite all|isolation|semantic|working [--target store] [--json] [-v]"""

import argparse
import asyncio
import json
import sys

from jarvis.memory.eval.runner import (
    SUITES,
    EvalReport,
    format_report,
    load_suites,
    load_working_suites,
    merge,
    run,
    run_working,
)
from jarvis.memory.eval.target import TARGETS


async def _run_all(names: list[str], target_name: str) -> EvalReport:
    reports = []
    store_cases = load_suites(names)
    if store_cases:
        reports.append(await run(store_cases, TARGETS[target_name]()))
    working_cases = load_working_suites(names)
    if working_cases:
        reports.append(await run_working(working_cases))
    return merge(*reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis.memory.eval")
    parser.add_argument("--suite", default="all", choices=("all", *SUITES))
    parser.add_argument("--target", default="store", choices=tuple(TARGETS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    names = list(SUITES) if args.suite == "all" else [args.suite]
    report = asyncio.run(_run_all(names, args.target))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report, args.verbose))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
