"""python -m jarvis.memory.eval --suite all|isolation|semantic [--target legacy] [--json] [-v]"""

import argparse
import asyncio
import json
import sys

from jarvis.memory.eval.runner import SUITES, format_report, load_suites, run
from jarvis.memory.eval.target import TARGETS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis.memory.eval")
    parser.add_argument("--suite", default="all", choices=("all", *SUITES))
    parser.add_argument("--target", default="legacy", choices=tuple(TARGETS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    names = list(SUITES) if args.suite == "all" else [args.suite]
    report = asyncio.run(run(load_suites(names), TARGETS[args.target]()))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report, args.verbose))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
