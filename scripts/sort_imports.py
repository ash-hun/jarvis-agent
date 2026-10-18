"""CLAUDE.md 의 import 순서(외부는 줄 길이 오름차순, 로컬은 내림차순)로 맞추거나 --check 로 검사한다."""

import ast
import sys
from pathlib import Path

LOCAL_ROOTS = ("jarvis", "tests")
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git"}


def _is_local(stmt: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(stmt, ast.ImportFrom):
        if stmt.level > 0:
            return True
        name = stmt.module or ""
    else:
        name = stmt.names[0].name
    return name.split(".")[0] in LOCAL_ROOTS


def _one_line(text: str) -> str:
    # 여러 줄 import 는 펼친 길이로 잰다. 첫 줄 "from x import (" 만 재면 순서가 뜻을 잃는다
    flat = " ".join(text.split())
    return flat.replace("( ", "(").replace(", )", ")").replace(" )", ")")


def _runs(body: list[ast.stmt]) -> list[list[ast.Import | ast.ImportFrom]]:
    runs: list[list[ast.Import | ast.ImportFrom]] = []
    current: list[ast.Import | ast.ImportFrom] = []
    for stmt in body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)) and not (
            isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
        ):
            current.append(stmt)
            continue
        if len(current) > 1:
            runs.append(current)
        current = []
        for field in ("body", "orelse", "finalbody"):
            runs.extend(_runs(getattr(stmt, field, None) or []))
        for handler in getattr(stmt, "handlers", None) or []:
            runs.extend(_runs(handler.body))
    if len(current) > 1:
        runs.append(current)
    return runs


def _render(run: list[ast.Import | ast.ImportFrom], lines: list[str]) -> list[str]:
    chunks: list[tuple[bool, str, list[str]]] = []
    start = run[0].lineno - 1
    for stmt in run:
        # 문 사이 주석은 바로 아래 import 에 붙여 함께 움직인다
        block = [ln for ln in lines[start : stmt.end_lineno] if ln.strip()]
        text = "".join(ln for ln in lines[stmt.lineno - 1 : stmt.end_lineno])
        chunks.append((_is_local(stmt), _one_line(text), block))
        start = stmt.end_lineno
    external = sorted((c for c in chunks if not c[0]), key=lambda c: (len(c[1]), c[1]))
    local = sorted((c for c in chunks if c[0]), key=lambda c: (-len(c[1]), c[1]))
    out = [ln for c in external for ln in c[2]]
    if external and local:
        out.append("\n")
    out.extend(ln for c in local for ln in c[2])
    return out


def sort_source(source: str) -> str:
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    runs = _runs(ast.parse(source).body)
    for run in sorted(runs, key=lambda r: r[0].lineno, reverse=True):
        lines[run[0].lineno - 1 : run[-1].end_lineno] = _render(run, lines)
    result = "".join(lines)
    return result if source.endswith("\n") or not source else result.rstrip("\n")


def _files(roots: list[str]) -> list[Path]:
    found: list[Path] = []
    for root in map(Path, roots):
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        found.extend(p for p in candidates if not SKIP_DIRS & set(p.parts))
    return found


def main(argv: list[str]) -> int:
    check = "--check" in argv
    changed = []
    for path in _files([a for a in argv if a != "--check"]):
        source = path.read_text()
        result = sort_source(source)
        if result != source:
            changed.append(path)
            if not check:
                path.write_text(result)
    for path in changed:
        print(f"{'would sort' if check else 'sorted'}: {path}")
    return 1 if check and changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
