"""[scripts] 기능소개 페이지 맨 위의 인포그래픽(특징 트리와 처리 흐름)을 사양 JSON 에서 SVG 로 그린다."""

import sys
import json
from typing import Any
from pathlib import Path
from dataclasses import field, dataclass
from scripts.docs_figures import OUT_DIR, esc, text_width

SPEC_DIR = Path(__file__).resolve().parent / "infographics" / "specs"
ICON_FILE = Path(__file__).resolve().parent / "infographics" / "icons.json"
WIDTH = 760
MARGIN = 20
COLORS = ("blue", "teal", "green", "orange", "red", "purple", "pink", "slate")
TITLE_FS = 22
TAGLINE_FS = 14
FEATURE_FS = 14.5
FEATURE_SUB_FS = 12.5
CARD_TITLE_FS = 13.5
CARD_BODY_FS = 12.5
LINE_H = 17
CIRCLE_R = 31
FLOW_GAP = 38  # 같은 줄 카드 사이. 화살표와 "예" 가 들어간다
PER_ROW = 4


@dataclass
class Card:
    kind: str
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    spec: dict[str, Any] = field(default_factory=dict)

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Info:
    name: str
    icons: dict[str, list[list[Any]]]
    parts: list[str] = field(default_factory=list)

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: str, cls: str, anchor: str = "middle") -> None:
        self.add(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{esc(s)}</text>')

    def icon(self, name: str, cx: float, cy: float, size: float) -> None:
        if name not in self.icons:
            raise SystemExit(f"{self.name}: 아이콘 '{name}' 이 icons.json 에 없다. --vendor 로 다시 고른다")
        s = size / 24
        body = "".join(
            f"<{tag} " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>" for tag, attrs in self.icons[name]
        )
        move = f"translate({cx - size / 2:.1f},{cy - size / 2:.1f}) scale({s:.3f})"
        self.add(f'<g class="if-icon" transform="{move}">{body}</g>')

    def rect(self, cls: str, x: float, y: float, w: float, h: float, rx: float = 0) -> None:
        self.add(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}"/>')

    def edge(self, pts: list[tuple[float, float]], head: bool = True) -> None:
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        marker = f' marker-end="url(#{self.name}-arrow)"' if head else ""
        self.add(f'<path class="if-edge" d="{d}"{marker}/>')

    def dot(self, x: float, y: float, r: float = 3.5) -> None:
        self.add(f'<circle class="if-dot" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')

    def svg(self, height: float, label: str) -> str:
        defs = (
            f'<marker id="{self.name}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path class="if-head" d="M0,1 L10,5 L0,9 z"/></marker>'
        )
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height:.0f}" class="if-svg" '
            f'role="img" aria-label="{esc(label)}">\n<defs>{defs}</defs>\n{body}\n</svg>\n'
        )


def wrap(text: str, fs: float, max_w: float) -> list[str]:
    """공백 단위로 줄을 나눈다. 한 낱말이 폭보다 길면 글자 단위로 자른다."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}" if line else word
        if text_width(trial, fs) <= max_w:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        for ch in word:
            if text_width(line + ch, fs) > max_w and line:
                lines.append(line)
                line = ""
            line += ch
    if line:
        lines.append(line)
    # 글자 단위로 자르다 문장 부호가 줄 머리에 남으면 앞 줄 끝으로 붙인다
    for i in range(len(lines) - 1, 0, -1):
        if lines[i][:1] in ",.)":
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:].strip()
    return [line for line in lines if line] or [""]


def color_of(spec: dict[str, Any], default: str) -> str:
    color = spec.get("color", default)
    if color not in COLORS:
        raise SystemExit(f"모르는 색 '{color}'. 쓸 수 있는 색: {', '.join(COLORS)}")
    return str(color)


# ── 머리: 제목 띠와 특징 트리 ──


def header(f: Info, spec: dict[str, Any], y: float) -> float:
    title = spec["title"]
    w = text_width(title, TITLE_FS) + 64
    x = (WIDTH - w) / 2
    f.add(f'<rect class="if-title" x="{x:.1f}" y="{y}" width="{w:.1f}" height="50" rx="12"/>')
    f.text(WIDTH / 2, y + 33, title, "if-title-t")
    y += 50
    tagline = spec.get("tagline", "")
    if tagline:
        for i, line in enumerate(wrap(tagline, TAGLINE_FS, 600)):
            f.text(WIDTH / 2, y + 24 + i * 20, line, "if-tagline")
        y += 24 + 20 * (len(wrap(tagline, TAGLINE_FS, 600)) - 1) + 8
    return y


def features(f: Info, items: list[dict[str, Any]], top: float) -> float:
    """제목 아래로 버스를 내리고, 특징마다 아이콘 원과 이름을 단다(참고: 유형 트리 인포그래픽)."""
    n = len(items)
    slot = (WIDTH - 2 * MARGIN) / n
    centers = [MARGIN + slot * (i + 0.5) for i in range(n)]
    bus_y = top + 22
    f.dot(WIDTH / 2, top + 4, 4)
    f.edge([(WIDTH / 2, top + 4), (WIDTH / 2, bus_y)], head=False)
    if n > 1:
        f.add(
            f'<path class="if-edge" d="M{centers[0]:.1f},{bus_y + 14:.1f} Q{centers[0]:.1f},{bus_y:.1f} '
            f"{centers[0] + 14:.1f},{bus_y:.1f} L{centers[-1] - 14:.1f},{bus_y:.1f} "
            f'Q{centers[-1]:.1f},{bus_y:.1f} {centers[-1]:.1f},{bus_y + 14:.1f}"/>'
        )
    cy = bus_y + 30 + CIRCLE_R
    bottom = cy + CIRCLE_R
    for cx, item in zip(centers, items, strict=True):
        start = bus_y + 14 if (n > 1 and cx in (centers[0], centers[-1])) else bus_y
        f.edge([(cx, start), (cx, cy - CIRCLE_R - 8)], head=False)
        f.dot(cx, cy - CIRCLE_R - 8)
        color = color_of(item, "blue")
        f.add(f'<circle class="if-ring" cx="{cx:.1f}" cy="{cy:.1f}" r="{CIRCLE_R + 4}"/>')
        f.add(f'<circle class="if-c-{color}" cx="{cx:.1f}" cy="{cy:.1f}" r="{CIRCLE_R}"/>')
        f.icon(item["icon"], cx, cy, 28)
        y = cy + CIRCLE_R + 24
        for line in wrap(item["label"], FEATURE_FS, slot - 12):
            f.text(cx, y, line, "if-feature")
            y += LINE_H + 1
        for line in wrap(item.get("sub", ""), FEATURE_SUB_FS, slot - 12) if item.get("sub") else []:
            f.text(cx, y, line, "if-feature-sub")
            y += LINE_H - 1
        bottom = max(bottom, y)
    return bottom + 6


# ── 처리 흐름: 색 카드와 예/아니오 분기 ──


def section_bar(f: Info, y: float, title: str) -> float:
    f.add(f'<rect class="if-bar" x="{MARGIN}" y="{y}" width="{WIDTH - 2 * MARGIN}" height="34" rx="8"/>')
    f.text(WIDTH / 2, y + 22.5, title, "if-bar-t")
    return y + 34


def rows_of(nodes: list[dict[str, Any]], per_row: int) -> list[list[dict[str, Any]]]:
    """줄마다 per_row 개. 판단이 줄 끝에 오면 '아니오' 가지와 줄바꿈 선이 겹쳐 다음 줄 처음으로 넘긴다."""
    rows: list[list[dict[str, Any]]] = []
    row: list[dict[str, Any]] = []
    for i, node in enumerate(nodes):
        row.append(node)
        last = i == len(nodes) - 1
        if len(row) == per_row and not last:
            if row[-1]["type"] == "decision" and len(row) > 1:
                rows.append(row[:-1])
                row = [row[-1]]
            else:
                rows.append(row)
                row = []
    if row:
        rows.append(row)
    return rows


def measure(node: dict[str, Any], w: float) -> Card:
    kind = node["type"]
    if kind == "decision":
        lines = wrap(node["q"], CARD_TITLE_FS, w - 24)
        return Card(kind, w=w, h=22 + LINE_H * len(lines), spec=node)
    head = wrap(node["title"], CARD_TITLE_FS, w - 40)
    body = wrap(node.get("body", ""), CARD_BODY_FS, w - 18) if node.get("body") else []
    head_h = 14 + LINE_H * len(head)
    return Card(kind, w=w, h=head_h + (12 + 16 * len(body) if body else 0), spec=node)


def draw_card(f: Info, c: Card) -> None:
    node = c.spec
    if c.kind == "decision":
        color = color_of(node, "slate")
        f.rect(f"if-decision if-s-{color}", c.x, c.y, c.w, c.h, min(c.h / 2, 18))
        lines = wrap(node["q"], CARD_TITLE_FS, c.w - 24)
        for i, line in enumerate(lines):
            f.text(c.x + c.w / 2, c.y + 16 + LINE_H * i + 4, line, "if-decision-t")
        return
    color = color_of(node, "green" if c.kind == "end" else "blue")
    head = wrap(node["title"], CARD_TITLE_FS, c.w - 40)
    body = wrap(node.get("body", ""), CARD_BODY_FS, c.w - 18) if node.get("body") else []
    head_h = 14 + LINE_H * len(head)
    extra = " if-end" if c.kind == "end" else ""
    f.rect(f"if-t-{color} if-s-{color}{extra}", c.x, c.y, c.w, c.h, 9)
    # 머리 띠는 위만 둥글게: 둥근 사각형 위에 아래 모서리를 덮는 사각형을 겹친다
    f.add(f'<rect class="if-c-{color}" x="{c.x:.1f}" y="{c.y:.1f}" width="{c.w:.1f}" height="{head_h:.1f}" rx="9"/>')
    if body:
        f.add(f'<rect class="if-c-{color}" x="{c.x:.1f}" y="{c.y + head_h - 9:.1f}" width="{c.w:.1f}" height="9"/>')
    icon = node.get("icon")
    text_x = c.x + c.w / 2 + (9 if icon else 0)
    if icon:
        widest = max(text_width(line, CARD_TITLE_FS) for line in head)
        f.icon(icon, text_x - widest / 2 - 12, c.y + head_h / 2, 15)
    for i, line in enumerate(head):
        f.text(text_x, c.y + 12 + LINE_H * i + 7, line, "if-card-t")
    for i, line in enumerate(body):
        f.text(c.x + c.w / 2, c.y + head_h + 18 + 16 * i, line, "if-card-b")


def flow(f: Info, nodes: list[dict[str, Any]], top: float, per_row: int) -> float:
    w = (WIDTH - 2 * MARGIN - (per_row - 1) * FLOW_GAP) / per_row
    y = top + 18
    prev: Card | None = None
    rows = rows_of(nodes, per_row)
    for r, row in enumerate(rows):
        cards = [measure(n, w) for n in row]
        row_h = max(c.h for c in cards)
        for i, c in enumerate(cards):
            c.x = MARGIN + i * (w + FLOW_GAP)
            c.y = y + (row_h - c.h) / 2
        if prev is not None:
            # 줄바꿈: 앞 줄 끝 카드 아래로 내려 왼쪽으로 돌아와 이 줄 첫 카드 위로 들어간다.
            # 끝 카드가 판단이면 아래는 '아니오' 자리라, 오른쪽으로 나가 아니오 카드 바깥으로 내려온다
            turn = y - 16
            first = cards[0]
            end = [(first.x + first.w / 2, turn), (first.x + first.w / 2, first.y)]
            if prev.kind == "decision":
                side = min(prev.x + prev.w + 14, WIDTH - 6)
                f.edge([(prev.x + prev.w, prev.cy), (side, prev.cy), (side, turn), *end])
                f.text(prev.x + prev.w + 7, prev.cy - 7, prev.spec.get("yes_label", "예"), "if-yes")
            else:
                f.edge([(prev.x + prev.w / 2, prev.y + prev.h), (prev.x + prev.w / 2, turn), *end])
        lane = 0.0
        for i, c in enumerate(cards):
            draw_card(f, c)
            row_center = y + row_h / 2
            if i + 1 < len(cards):
                nxt = cards[i + 1]
                f.edge([(c.x + c.w, row_center), (nxt.x - 2, row_center)])
                if c.kind == "decision":
                    f.text(c.x + c.w + FLOW_GAP / 2, row_center - 7, c.spec.get("yes_label", "예"), "if-yes")
            if c.kind == "decision" and c.spec.get("no"):
                chip_lines = wrap(c.spec["no"], CARD_BODY_FS, c.w - 22)
                chip_h = 12 + 16 * len(chip_lines)
                chip_y = c.y + c.h + 30
                f.edge([(c.x + c.w / 2, c.y + c.h), (c.x + c.w / 2, chip_y - 2)])
                f.text(c.x + c.w / 2 + 8, c.y + c.h + 19, c.spec.get("no_label", "아니오"), "if-no", "start")
                no_color = color_of({"color": c.spec.get("no_color", "red")}, "red")
                f.rect(f"if-t-{no_color} if-s-{no_color} if-chip", c.x + 10, chip_y, c.w - 20, chip_h, 7)
                for j, line in enumerate(chip_lines):
                    f.text(c.x + c.w / 2, chip_y + 19 + 16 * j, line, "if-chip-t")
                lane = max(lane, chip_y + chip_h - (y + row_h))
        prev = cards[-1]
        y += row_h + lane + (44 if r < len(rows) - 1 else 0)
    return y + 14


def build(spec: dict[str, Any], icons: dict[str, list[list[Any]]]) -> str:
    f = Info(f"info-{spec['name']}", icons)
    y = header(f, spec, 14)
    if spec.get("features"):
        y = features(f, spec["features"], y + 4)
    if spec.get("flow"):
        y = section_bar(f, y + 10, spec.get("flow_title", "처리 흐름"))
        y = flow(f, spec["flow"], y, int(spec.get("per_row", PER_ROW)))
    return f.svg(y + 6, f"{spec['title']}: {spec.get('tagline', '')}")


def used_icons(specs: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for spec in specs:
        names.update(item["icon"] for item in spec.get("features", []))
        names.update(node["icon"] for node in spec.get("flow", []) if node.get("icon"))
    return names


def load_specs() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SPEC_DIR.glob("*.json"))]


def vendor(icon_nodes: Path, specs: list[dict[str, Any]]) -> None:
    """lucide-static 의 icon-nodes.json 에서 사양이 쓰는 아이콘만 icons.json 으로 옮긴다."""
    every = json.loads(icon_nodes.read_text(encoding="utf-8"))
    names = sorted(used_icons(specs))
    missing = [n for n in names if n not in every]
    if missing:
        raise SystemExit(f"lucide 에 없는 아이콘: {', '.join(missing)}")
    ICON_FILE.write_text(
        json.dumps({n: every[n] for n in names}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{ICON_FILE} ({len(names)}개)")


def main() -> None:
    specs = load_specs()
    if len(sys.argv) == 3 and sys.argv[1] == "--vendor":
        vendor(Path(sys.argv[2]), specs)
        return
    icons = json.loads(ICON_FILE.read_text(encoding="utf-8"))
    only = set(sys.argv[1:])
    for spec in specs:
        if only and spec["name"] not in only:
            continue
        out = OUT_DIR / f"info-{spec['name']}.svg"
        out.write_text(build(spec, icons), encoding="utf-8")
        print(out)


if __name__ == "__main__":
    main()
