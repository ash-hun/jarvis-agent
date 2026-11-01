"""Generates the paper-style figures at the top of each docs feature page as SVG files under website/src/figures/."""

import sys
from pathlib import Path
from dataclasses import dataclass, field

OUT_DIR = Path(__file__).resolve().parent.parent / "website" / "src" / "figures"
WIDTH = 760
# 문서 칸에서 그림은 760 단위가 약 590px 로 줄어든다. 그 배율에서 제목이 11px, 부제가 9.5px 아래로 내려가지 않는 크기다
TITLE_FS = 15
SUB_FS = 12.5
CODE_FS = 12
TCODE_FS = 13
PAD_X = 12
BOX_H = 44
BOX_H_SUB = 58
GATE_EXTRA = 10  # 둥근 끝이 먹는 폭
LINE_H = 19

# 모든 구조 그림이 같은 뜻으로 쓰는 표기. 그림에 쓰인 것만 범례에 나온다
LEGEND = [
    ("edge-accent", "주 경로"),
    ("edge", "흐름"),
    ("edge-deny", "거부, 실패"),
    ("edge-muted", "배경, 선택"),
    ("gate", "판단"),
    ("store", "저장소"),
    ("accent", "강조"),
]


def text_width(s: str, fs: float, mono: bool = False) -> float:
    if mono:
        return sum((1.0 if 0xAC00 <= ord(ch) <= 0xD7A3 else 0.6) * fs for ch in s)
    w = 0.0
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F:
            w += 0.93 * fs
        elif ch == " ":
            w += 0.27 * fs
        elif ch.isupper():
            w += 0.64 * fs
        elif ch in "ilj.,:;'|!()[]":
            w += 0.3 * fs
        elif o > 0x2000:
            w += 1.0 * fs
        else:
            w += 0.56 * fs
    return w


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def left(self) -> tuple[float, float]:
        return (self.x, self.cy)

    @property
    def right(self) -> tuple[float, float]:
        return (self.x + self.w, self.cy)

    @property
    def top(self) -> tuple[float, float]:
        return (self.cx, self.y)

    @property
    def bottom(self) -> tuple[float, float]:
        return (self.cx, self.y + self.h)

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h


@dataclass
class Fig:
    name: str
    height: float
    label: str
    parts: list[str] = field(default_factory=list)
    used: set[str] = field(default_factory=set)
    legend_names: dict[str, str] = field(default_factory=dict)
    rects: list[tuple[str, Box]] = field(default_factory=list)

    def _warn(self, msg: str) -> None:
        print(f"[{self.name}] {msg}", file=sys.stderr)

    def _keep(self, title: str, b: Box) -> None:
        self.rects.append((title, b))

    # ── 도형 ──
    def panel(self, x, y, w, h, label="", bottom=False):
        self.parts.append(f'<rect class="pf-panel" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>')
        if label:
            self.parts.append(
                f'<text class="pf-plabel" x="{x + 12}" y="{y + h - 10 if bottom else y + 21}">{esc(label)}</text>'
            )

    def need(self, title: str, sub: str = "", code: bool = False, tcode: bool = False) -> float:
        tw = text_width(title, TCODE_FS, True) if tcode else text_width(title, TITLE_FS) * 1.04
        sw = text_width(sub, CODE_FS if code else SUB_FS, code) if sub else 0
        return max(tw, sw) + 2 * PAD_X

    def _size(self, title, sub, code, w, h, tcode=False):
        need = self.need(title, sub, code, tcode)
        if w and need > w + 2:
            self._warn(f"'{title}' / '{sub}' needs {need:.0f} > w {w}")
        return (w or round(need + 4), h or (BOX_H_SUB if sub else BOX_H))

    def _labels(self, cx, cy, title, sub, code, title_cls="pf-t", tcode=False):
        if tcode:
            title_cls += " pf-tcode"
        if sub:
            self.parts.append(
                f'<text class="{title_cls}" x="{cx:.1f}" y="{cy - 3:.1f}" text-anchor="middle">{esc(title)}</text>'
            )
            cls = "pf-code" if code else "pf-s"
            self.parts.append(
                f'<text class="{cls}" x="{cx:.1f}" y="{cy + 15:.1f}" text-anchor="middle">{esc(sub)}</text>'
            )
        else:
            self.parts.append(
                f'<text class="{title_cls}" x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle">{esc(title)}</text>'
            )

    def box(self, x, y, title, sub="", kind="", code=False, w=None, h=None, center=False, tcode=False) -> Box:
        w, h = self._size(title, sub, code, w, h, tcode)
        if center:
            x -= w / 2
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        if kind:
            self.used.add("box-" + kind if kind != "accent" else "accent")
        self.parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="6"/>')
        tcls = "pf-t pf-t--" + kind if kind else "pf-t"
        self._labels(x + w / 2, y + h / 2, title, sub, code, tcls, tcode)
        b = Box(x, y, w, h)
        self._keep(title, b)
        return b

    def gate(self, x, y, title, sub="", code=False, w=None, h=None, center=False) -> Box:
        w, h = self._size(title, sub, code, w, h)
        w += GATE_EXTRA
        if center:
            x -= w / 2
        self.used.add("gate")
        self.parts.append(f'<rect class="pf-gate" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="{h / 2}"/>')
        self._labels(x + w / 2, y + h / 2, title, sub, code)
        b = Box(x, y, w, h)
        self._keep(title, b)
        return b

    def store(self, x, y, title, sub="", code=False, w=None, h=None, center=False) -> Box:
        w, h = self._size(title, sub, code, w, h)
        h += 8
        if center:
            x -= w / 2
        self.used.add("store")
        self._cylinder(x, y, w, h)
        self._labels(x + w / 2, y + h / 2 + 3, title, sub, code)
        b = Box(x, y, w, h)
        self._keep(title, b)
        return b

    def _cylinder(self, x: float, y: float, w: float, h: float, e: float = 5) -> None:
        self.parts.append(
            f'<path class="pf-store" d="M{x:.1f},{y + e} a{w / 2:.1f},{e} 0 0,0 {w},0 a{w / 2:.1f},{e} 0 0,0 {-w},0 '
            f'v{h - 2 * e} a{w / 2:.1f},{e} 0 0,0 {w},0 v{-(h - 2 * e)}"/>'
        )

    def badge(self, x, y, n):
        self.parts.append(f'<circle class="pf-badge" cx="{x:.1f}" cy="{y:.1f}" r="10"/>')
        self.parts.append(f'<text class="pf-badge-t" x="{x:.1f}" y="{y + 4.2:.1f}" text-anchor="middle">{n}</text>')

    def step(self, b: Box, n: int, gate: bool = False) -> None:
        """단계 번호를 칸의 왼쪽 위 모서리에 얹는다. 알약은 둥근 끝 안쪽으로 조금 들인다."""
        self.badge(b.x + (b.h * 0.3 if gate else 2), b.y + 2, n)

    def text(self, x, y, s, cls="pf-s", anchor="start"):
        self.parts.append(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{esc(s)}</text>')

    def vtext(self, x, y, s, cls="pf-s"):
        self.parts.append(
            f'<text class="{cls}" x="{x}" y="{y}" text-anchor="middle" transform="rotate(-90 {x} {y})">{esc(s)}</text>'
        )

    def box_lines(self, x, y, w, title, lines, kind="", code=False, line_h=LINE_H) -> Box:
        h = 38 + line_h * len(lines)
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        if kind == "accent":
            self.used.add("accent")
        need = max(
            [text_width(title, TITLE_FS) * 1.04] + [text_width(s, CODE_FS if code else SUB_FS, code) for s in lines]
        )
        # 여러 줄 칸은 줄마다 길이가 달라 양옆 여백을 반만 요구한다
        if need + PAD_X > w + 2:
            self._warn(f"'{title}' lines need {need + PAD_X:.0f} > w {w}")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        tcls = "pf-t pf-t--" + kind if kind else "pf-t"
        self.text(x + w / 2, y + 24, title, tcls, "middle")
        for i, line in enumerate(lines):
            self.text(x + w / 2, y + 45 + i * line_h, line, "pf-code" if code else "pf-s", "middle")
        b = Box(x, y, w, h)
        self._keep(title, b)
        return b

    def chip(self, x, y, s, kind="", w=28, h=24) -> Box:
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="4"/>')
        self.text(x + w / 2, y + h / 2 + 4.5, s, "pf-chip", "middle")
        return Box(x, y, w, h)

    def bar(self, x, y, w, s, kind="", h=18):
        cls = "pf-bar" + (f" pf-bar--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>')
        if s:
            self.text(x + w / 2, y + h / 2 + 4.5, s, "pf-bar-t" + (f" pf-bar-t--{kind}" if kind else ""), "middle")

    def edge(self, pts, kind="", label="", at=None, anchor="middle", dy=-6, head=True):
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        cls = "pf-edge" + (f" pf-edge--{kind}" if kind else "")
        self.used.add("edge" + (f"-{kind}" if kind else ""))
        marker = f' marker-end="url(#{self.name}-h{("-" + kind) if kind else ""})"' if head else ""
        self.parts.append(f'<path class="{cls}" d="{d}"{marker}/>')
        if label:
            if at is None:
                (x1, y1), (x2, y2) = pts[0], pts[1]
                at = ((x1 + x2) / 2, (y1 + y2) / 2)
            cls = "pf-elabel" + (f" pf-elabel--{kind}" if kind else "")
            self.parts.append(
                f'<text class="{cls}" x="{at[0]:.1f}" y="{at[1] + dy:.1f}" text-anchor="{anchor}">{esc(label)}</text>'
            )

    # ── 범례 ──
    def _legend_glyph(self, key: str, x: float, cy: float) -> float:
        """범례 기호 하나를 그리고 그 폭을 돌려준다."""
        if key.startswith("edge"):
            kind = key[5:]
            cls = "pf-edge" + (f" pf-edge--{kind}" if kind else "")
            marker = f"url(#{self.name}-h{('-' + kind) if kind else ''})"
            self.parts.append(f'<path class="{cls}" d="M{x},{cy} L{x + 30},{cy}" marker-end="{marker}"/>')
            return 30
        if key == "gate":
            self.parts.append(f'<rect class="pf-gate" x="{x}" y="{cy - 8}" width="30" height="16" rx="8"/>')
            return 30
        if key == "store":
            self._cylinder(x, cy - 9, 22, 18, 3.5)
            return 22
        if key == "box-muted":
            self.parts.append(
                f'<rect class="pf-box pf-box--muted" x="{x}" y="{cy - 8}" width="28" height="16" rx="3"/>'
            )
            return 28
        self.parts.append(f'<rect class="pf-box pf-box--accent" x="{x}" y="{cy - 8}" width="28" height="16" rx="3"/>')
        return 28

    def _legend(self) -> None:
        items = [(k, self.legend_names.get(k, v)) for k, v in LEGEND if k in self.used]
        # 점선 칸만 있고 점선 화살표가 없으면 같은 뜻의 칸 기호로 보인다
        if "box-muted" in self.used and "edge-muted" not in self.used:
            items.append(("box-muted", self.legend_names.get("box-muted", "배경, 선택")))
        if not items:
            return
        x, cy = 20.0, self.height + 8
        for key, name in items:
            span = 30 + 8 + text_width(name, 12.5) + 22
            if x + span > WIDTH - 10:
                x, cy = 20.0, cy + 24
            gw = self._legend_glyph(key, x, cy)
            self.text(x + gw + 8, cy + 4.5, name, "pf-legend")
            x += gw + 8 + text_width(name, 12.5) + 22
        self.height = cy + 18

    def _check(self) -> None:
        """칸끼리 겹치면 알린다. 그림을 고친 뒤 눈으로 보기 전에 거르는 용도다."""
        for i, (ta, a) in enumerate(self.rects):
            for tb, b in self.rects[i + 1 :]:
                if a.x < b.x2 - 1 and b.x < a.x2 - 1 and a.y < b.y2 - 1 and b.y < a.y2 - 1:
                    self._warn(f"overlap '{ta}' and '{tb}'")
            if a.x < 16 or a.x2 > WIDTH - 16 or a.y2 > self.height:
                self._warn(f"'{ta}' outside the canvas")

    def svg(self) -> str:
        self._check()
        self._legend()
        heads = "".join(
            f'<marker id="{self.name}-h{suffix}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" '
            f'orient="auto-start-reverse"><path class="pf-head{cls}" d="M0,1 L10,5 L0,9 z"/></marker>'
            for suffix, cls in (
                ("", ""),
                ("-accent", " pf-head--accent"),
                ("-deny", " pf-head--deny"),
                ("-muted", " pf-head--muted"),
            )
        )
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {self.height:g}" class="pf-svg" '
            f'role="img" aria-label="{esc(self.label)}">\n<defs>{heads}</defs>\n{body}\n</svg>\n'
        )


def spread_x(widths: list[float], x0: float, x1: float) -> list[float]:
    """폭이 정해진 칸들을 x0 에서 x1 까지 같은 간격으로 놓을 왼쪽 x 들."""
    gap = (x1 - x0 - sum(widths)) / max(1, len(widths) - 1)
    xs, x = [], x0
    for w in widths:
        xs.append(x)
        x += w + gap
    return xs


# ── 그림 ──


def architecture() -> Fig:
    f = Fig(
        "architecture",
        404,
        "JARVIS 의 계층 구조",
        legend_names={"edge": "쓴다(의존)", "edge-accent": "의존 방향", "edge-muted": "외부 호출"},
    )
    rows = [
        ("ui/  화면", "TUI 와 Web HUD. 같은 AppAssembly 를 받아 화면만 다르다"),
        ("app/  조립", "InfraBuilder 가 설정 하나로 도구, 메모리, 저장소, 보안을 만든다"),
        ("core/  오케스트레이션과 정책", "AgentSession, 보안, 도구, 승인, proactive, 스케줄러, 목표, Focus"),
        ("agent_layer/  에이전트 런타임", "에이전트 루프, 내적 사고 엔진, 열린 약속, 세션 저장소"),
        ("model_layer/  LLM 추상화", "프로바이더마다 stream() 하나, 임베딩, decision model"),
    ]
    f.panel(16, 12, 728, 380)
    boxes = [f.box(64, 30 + i * 72, t, sub, w=440, kind="accent" if i == 2 else "") for i, (t, sub) in enumerate(rows)]
    for up, down in zip(boxes, boxes[1:], strict=False):
        f.edge([up.bottom, down.top], "")
    f.edge([(44, 36), (44, 372)], "accent")
    f.vtext(36, 204, "의존 방향. 아래층은 위층을 모른다", "pf-elabel pf-elabel--accent")
    f.box(528, 30, "common/", "structlog 로거, 어느 층이든", w=208, kind="muted")
    f.box(528, 102, "voice/", "STT, TTS. ui 와 app 이 쓴다", w=208)
    mem = f.box(528, 174, "memory/", "작업 기억, 장기 기억", w=208, h=130)
    f.edge([boxes[2].right, (mem.x, boxes[2].cy)], "")
    f.edge([boxes[3].right, (mem.x, boxes[3].cy)], "")
    prov = f.box(528, 318, "프로바이더", "anthropic, openai, gemini 외 2", w=208, kind="muted")
    f.edge([boxes[4].right, prov.left], "muted", head=False)
    return f


def inner_thought() -> Fig:
    f = Fig("inner-thought", 506, "내적 사고 한 번의 흐름과 시점")
    f.panel(16, 12, 728, 300, "(a) 사고 한 번")
    ins = [
        ("사용자 입력", "io"),
        ("열린 약속", ""),
        ("사용자 모델", ""),
        ("회상한 기억 5건", ""),
        ("최근 대화 8턴", ""),
        ("페르소나", ""),
        ("외부 이벤트 (성찰)", "muted"),
    ]
    ib = [f.box(28, 44 + i * 37, t, w=146, h=30, kind=k) for i, (t, k) in enumerate(ins)]
    r = f.box(198, 70, "템플릿 렌더", "inner_thought.md", code=True, w=146)
    m = f.box(198, 196, "사고 모델 호출", "도구 없음, JSON 응답", w=146, kind="accent")
    for b in ib:
        f.edge([b.right, (186, b.cy)], "", head=False)
    f.edge([(186, ib[0].cy), (186, ib[-1].cy)], "", head=False)
    f.edge([(186, r.cy), r.left], "")
    f.edge([r.bottom, m.top], "accent")
    fr = f.box_lines(
        368,
        m.cy - 76,
        150,
        "ThoughtFrame",
        ["decision", "confidence", "utterance", "needs_background", "filler", "proactive_actions"],
        code=True,
    )
    f.edge([m.right, (fr.x, m.cy)], "accent")
    outs = [
        ("💭 한 줄", "결정과 확신도"),
        ("시스템 프롬프트", "[내적 사고] 블록"),
        ("Dual channel", "filler 먼저"),
        ("다음 턴에 한 번", "router 가 think 일 때"),
    ]
    ob = [f.box(552, 44 + i * 64, t, sub, w=184, h=54) for i, (t, sub) in enumerate(outs)]
    for b in ob:
        f.edge([(fr.x2, fr.cy), (536, fr.cy), (536, b.cy), b.left], "")
    f.step(r, 1)
    f.step(m, 2)
    f.step(fr, 3)
    f.panel(16, 324, 728, 170, "(b) 사고와 메인 응답의 순서 (request_timing)")
    rows = [
        ("before", (0, 90), (90, 210), "메인 응답"),
        ("race (기본)", (0, 90), (27, 210), "3초까지 기다린 뒤 메인 응답"),
        ("after", (120, 210), (0, 120), "메인 응답"),
    ]
    x0, scale = 160, 2.6
    for i, (name, think, main, main_label) in enumerate(rows):
        y = 356 + i * 44
        f.text(146, y + 22, name, "pf-code", "end")
        f.bar(x0 + think[0] * scale, y, (think[1] - think[0]) * scale, "사고", "accent", h=18)
        f.bar(x0 + main[0] * scale, y + 20, (main[1] - main[0]) * scale, main_label, h=18)
    return f


def proactive() -> Fig:
    f = Fig("proactive", 722, "먼저 말하기 전에 지나는 게이트와 피드백 학습")
    f.panel(16, 12, 728, 498, "(a) 성찰 한 번")

    def column(cx: float, y: float, specs: list[tuple[str, str, str, str]]) -> list[Box]:
        out = []
        for kind, title, sub, extra in specs:
            h = 54 if sub else 40
            if kind == "gate":
                b = f.gate(cx, y, title, sub, h=h, center=True)
            else:
                b = f.box(cx, y, title, sub, kind=extra, h=h, center=True, code=extra == "code")
            out.append(b)
            y += h + 14
        return out

    trig, g1, g0, g2, g3, th = column(
        140,
        58,
        [
            ("box", "트리거", "주기, 이벤트", "io"),
            ("gate", "답 대기 없음", "", ""),
            ("gate", "대화 있음", "", ""),
            ("gate", "말할 근거", "약속, 새 이벤트", ""),
            ("gate", "입력이 바뀜", "15분마다", ""),
            ("box", "성찰 사고", "+ decision model", ""),
        ],
    )
    g4, g5, g6, g7, g8, g9, out = column(
        420,
        58,
        [
            ("gate", "되풀이 아님", "", ""),
            ("gate", "act, ask", "", ""),
            ("gate", "확신도 ≥ θ", "", ""),
            ("gate", "문장 있음", "", ""),
            ("gate", "쿨다운 지남", "", ""),
            ("gate", "답하는 중 아님", "Focus 도 아님", ""),
            ("box", "에이전트가 먼저 건네는 말", "대화 기록에 남는다", "accent"),
        ],
    )
    f.text(trig.x2 + 12, trig.cy + 5, "사고 전", "pf-elabel")
    f.text(g4.x2 + 12, g4.cy + 5, "사고 뒤", "pf-elabel")
    for a, b in ((trig, g1), (g1, g0), (g0, g2), (g2, g3), (g3, th), (g4, g5), (g5, g6), (g6, g7), (g7, g8)):
        f.edge([a.bottom, b.top], "accent")
    f.edge([g8.bottom, g9.top], "accent")
    f.edge([g9.bottom, out.top], "accent")
    f.edge([th.right, (270, th.cy), (270, 52), (g4.cx - 40, 52), (g4.cx - 40, g4.y)], "accent")
    auto = f.box(560, g8.y - 9, "저위험 자율 행동", "proactive_actions", code=True, w=160)
    f.edge([g8.right, auto.left], "", "쿨다운 뒤", at=((g8.x2 + auto.x) / 2, g8.cy))
    # 어느 게이트에서든 막히면 침묵한다. 게이트마다 선을 따로 긋지 않고 양옆의 버스로 모은다
    sil = f.box(66, 452, "침묵", "이유만 로그에 남긴다", kind="deny", w=210, h=44)
    for g in (g1, g0, g2, g3):
        f.edge([g.left, (40, g.cy)], "deny", head=False)
    f.edge([(40, g1.cy), (40, sil.cy), sil.left], "deny")
    for g in (g4, g5, g6, g7, g8, g9):
        f.edge([g.left, (300, g.cy)], "deny", head=False)
    f.edge([(300, g4.cy), (300, sil.cy), sil.right], "deny")

    f.panel(16, 522, 240, 188, "(c) Dual channel")
    g = f.gate(136, 560, "오래 걸릴 요청인가", "needs_background", code=True, center=True)
    fl = f.box(26, 640, "filler 먼저", kind="accent", w=104, h=56)
    mn = f.box(142, 640, "메인 응답", "뒤에서 돈다", w=104, h=56)
    f.edge([(g.cx - 30, g.y2), (fl.cx, fl.y)], "accent", "예", at=(g.cx - 26, 636), anchor="middle", dy=0)
    f.edge([(g.cx + 30, g.y2), (mn.cx, mn.y)], "")

    f.panel(268, 522, 476, 188, "(b) 피드백 학습")
    react = f.box(280, 588, "그 뒤 첫 말", "묻지 않고 읽는다", w=114, kind="io")
    opts = ["받아들임, θ − 0.05", "거절, θ + 0.05", "딴 얘기, 무응답, θ + 0.025"]
    ob = [f.box(428, 556 + i * 46, t, w=206, h=36) for i, t in enumerate(opts)]
    for b in ob:
        f.edge([react.right, (410, react.cy), (410, b.cy), b.left], "")
    th_box = f.box(656, 588, "임계치 θ", "0.3 ~ 0.95", w=80, kind="accent")
    for b in ob:
        f.edge([b.right, (645, b.cy), (645, th_box.cy)], "", head=False)
    f.edge([(645, th_box.cy), th_box.left], "")
    f.edge(
        [th_box.top, (th_box.cx, 516), (734, 516), (734, g6.cy), g6.right],
        "accent",
        "θ 를 옮긴다",
        at=((g6.x2 + 734) / 2 + 30, g6.cy),
    )
    return f


def memory() -> Fig:
    f = Fig("memory", 430, "턴마다 기억을 읽는 길과 장기 기억에 쓰는 순간")
    f.panel(16, 12, 728, 270, "(a) 매 턴 읽기")
    specs = [
        ("세션 히스토리", "", "io"),
        ("턴 창", "최근 3턴만", ""),
        ("회상 거르기", "창 안의 턴, 사고 로그 빼기", ""),
    ]
    ws = [f.need(t, s) + 4 for t, s, _ in specs]
    row = [
        f.box(x, 48, t, s, kind=k, w=w, h=58) for (t, s, k), x, w in zip(specs, spread_x(ws, 28, 474), ws, strict=True)
    ]
    pr = f.box_lines(
        496,
        36,
        208,
        "프롬프트",
        [
            "[핵심 사실] 3건",
            "[장기 기억] 회상 3건",
            "[절차 기억] 스킬",
            "[작업 패턴] 2건까지",
            "[작업 공유 메모리] 위임 중",
            "최근 3턴",
        ],
        kind="accent",
    )
    llm = f.box(560, 212, "LLM", w=80, h=40)
    for a, b in zip(row, row[1:], strict=False):
        f.edge([a.right, b.left], "accent")
    f.edge([row[-1].right, (pr.x, row[-1].cy)], "accent")
    f.edge([(llm.cx, pr.y2), llm.top], "accent")
    ltm = f.store(28, 142, "장기 기억", "프로필 공유, 일화와 절차는 정책이 연 것만", w=286)
    f.edge([ltm.right, (pr.x, ltm.cy)], "", "회상: 키워드 + 벡터, 점수", at=((ltm.x2 + pr.x) / 2, ltm.cy))
    skills = f.store(326, 204, "스킬 레지스트리", "읽기만, 스킬 파일이 정본", w=176)
    f.edge([skills.right, (524, skills.cy), (524, pr.y2)], "")
    f.panel(16, 294, 728, 124, "(b) 턴마다 그 턴을 일화로 쓰고, 나머지는 정해진 순간에만 쓴다", bottom=True)
    writes = [
        ("/remember", "프로필 사실", False),
        ("턴 끝", "그 턴을 일화로", False),
        ("통합", "사실 뽑기, 절차 초안", False),
        ("사고, 저널, 위임", "일화", False),
        ("remember_task_pattern", "에이전트별 절차", True),
    ]
    ws = [f.need(t, s, tcode=tc) + 4 for t, s, tc in writes]
    wb = [
        f.box(x, 324, t, s, w=w, tcode=tc) for (t, s, tc), x, w in zip(writes, spread_x(ws, 28, 736), ws, strict=True)
    ]
    for b in wb:
        f.edge([b.top, (b.cx, 312)], "", head=False)
    f.edge([(wb[0].cx, 312), (wb[-1].cx, 312)], "", head=False)
    f.edge([(ltm.x + 120, 312), (ltm.x + 120, ltm.y2)], "", "쓰기", at=(ltm.x + 128, 300), anchor="start", dy=0)
    return f


def sessions() -> Fig:
    f = Fig("sessions", 366, "세션의 저장, 분기, 종료")
    f.panel(16, 12, 728, 180, "(a) 세션과 분기")
    f.text(32, 64, "세션 A", "pf-t")
    f.text(32, 82, "agent: main", "pf-code")
    seq = ["U", "A", "T", "A", "U", "A"]
    xa = [142 + i * 36 for i in range(len(seq))]
    for x, k in zip(xa, seq, strict=True):
        f.chip(x, 56, k, "accent" if k == "U" else "")
    end = f.box(410, 39, "종료 또는 유휴", "셧다운, 180초 조용하면", w=150)
    hooks = f.box(586, 39, "통합", "사실 뽑기, 절차 초안", w=150)
    f.edge([(xa[-1] + 30, 68), end.left], "muted")
    f.edge([end.right, hooks.left], "")
    f.text(32, 150, "세션 B", "pf-t")
    f.text(32, 168, "parent_id = A", "pf-code")
    for i in range(4):
        f.chip(xa[i], 140, seq[i], "muted")
    for i, k in enumerate(["U", "A"]):
        f.chip(xa[4 + i], 140, k, "accent" if k == "U" else "")
    f.edge([(xa[3] + 14, 80), (xa[3] + 14, 138)], "accent", "/branch, ⑂", at=(xa[3] + 22, 114), anchor="start", dy=0)
    f.text(410, 157, "메시지를 복사한다. 이후 변경은 서로 전파되지 않는다", "pf-s")
    f.panel(16, 204, 728, 150, "(b) 한 턴이 저장되는 때")
    specs = [
        ("사용자 메시지", "턴 시작 때 바로 저장"),
        ("에이전트 루프", "LLM 과 도구, 최대 20턴"),
        ("나머지 메시지", "루프가 끝난 뒤 한꺼번에"),
    ]
    ws = [f.need(t, s) + 4 for t, s in specs] + [f.need("저장소", "jsonl, Postgres") + 4]
    xs = spread_x(ws, 28, 736)
    u, lp, sv = (
        f.box(x, 240, t, s, w=w, kind="io" if i == 0 else "")
        for i, ((t, s), x, w) in enumerate(zip(specs, xs[:3], ws[:3], strict=True))
    )
    st = f.store(xs[3], 236, "저장소", "jsonl, Postgres", w=ws[3])
    f.edge([u.right, lp.left], "accent")
    f.edge([lp.right, sv.left], "accent")
    f.edge([sv.right, st.left], "accent")
    f.edge([u.bottom, (u.cx, 318), (st.cx, 318), st.bottom], "")
    f.text(380, 342, "루프 도중에 죽으면 사용자 메시지만 남는다", "pf-note", "middle")
    for i, b in enumerate((u, lp, sv)):
        f.step(b, i + 1)
    return f


def tools_and_approval() -> Fig:
    f = Fig("tools-and-approval", 400, "도구 호출 한 번이 지나는 검사와 승인")
    f.panel(16, 12, 728, 376, "")
    specs = [
        ("box", "도구 호출", "LLM 이 고름", False),
        ("gate", "허용 목록", "", False),
        ("gate", "플러그인", "before_tool_call", True),
        ("gate", "승인이 필요한가", "", False),
        ("gate", "규칙에 맞나", "공용, 에이전트별", False),
    ]
    ws = [f.need(t, s, c) + 4 + (GATE_EXTRA if k == "gate" else 0) for k, t, s, c in specs]
    row = []
    for (k, t, s, c), x, w in zip(specs, spread_x(ws, 28, 736), ws, strict=True):
        if k == "gate":
            row.append(f.gate(x, 34, t, s, code=c, w=w - GATE_EXTRA, h=58))
        else:
            row.append(f.box(x, 34, t, s, kind="io", w=w, h=58))
    call, g1, g2, g3, g4 = row
    for a, b in zip(row, row[1:], strict=False):
        f.edge([a.right, b.left], "accent")
    ex = f.box(446, 172, "실행", w=76, h=50, kind="accent")
    f.edge(
        [g3.bottom, (g3.cx, 140), (ex.cx + 14, 140), (ex.cx + 14, ex.y)],
        "accent",
        "아니오",
        at=(g3.cx + 6, 124),
        anchor="start",
        dy=0,
    )
    f.edge(
        [(g4.cx - 40, g4.y2), (g4.cx - 40, 140), (ex.cx + 14, 140)],
        "accent",
        "맞음",
        at=(g4.cx - 34, 124),
        anchor="start",
        dy=0,
        head=False,
    )
    ask = f.box(g4.cx, 168, "사람에게 묻기", "120초", w=124, center=True)
    f.edge([(g4.cx + 24, g4.y2), (g4.cx + 24, ask.y)], "", "아니오", at=(g4.cx + 30, 150), anchor="start", dy=0)
    f.edge([ask.left, ex.right], "accent", "ALLOW")
    rule = f.store(ask.x2 - 182, 252, "규칙 저장", "approvals/<agent>.yaml", code=True, w=182)
    f.edge([ask.bottom, (ask.cx, rule.y)], "", "ALWAYS", at=(ask.cx + 6, 244), anchor="start", dy=0)
    f.edge([rule.left, (ex.cx, rule.cy), ex.bottom], "")
    after = f.box(270, 172, "after_tool_call", w=150, h=50, tcode=True)
    res = f.box(28, 168, "결과를 LLM 에", "모두 final 이면 그 글이 답", w=206)
    f.edge([ex.left, after.right], "accent")
    f.edge([after.left, res.right], "accent")
    lane = f.box(28, 336, "is_error 결과가 LLM 에 가고 루프는 이어진다", w=402, h=36, kind="deny")
    stop = f.box(448, 336, "모두 거부면 정해진 한 줄로 끝낸다", w=258, h=36, kind="deny")
    f.edge(
        [g1.bottom, (g1.cx, 112), (252, 112), (252, lane.y)], "deny", "없음", at=(g1.cx + 6, 106), anchor="start", dy=0
    )
    f.edge(
        [g2.bottom, (g2.cx, 128), (436, 128), (436, lane.y)], "deny", "block", at=(g2.cx + 6, 122), anchor="start", dy=0
    )
    f.edge(
        [ask.right, (738, ask.cy), (738, stop.cy), stop.right],
        "deny",
        "DENY, 시간 초과",
        at=(732, stop.cy - 22),
        anchor="end",
        dy=0,
    )
    f.edge([(res.cx, lane.y), (res.cx, res.y2)], "deny")
    for i, b in enumerate((g1, g2, g3, g4)):
        f.step(b, i + 1, gate=True)
    f.step(ask, 5)
    return f


def open_loop() -> Fig:
    f = Fig("open-loop", 524, "Open Loop 의 저장과 닫힘")
    f.panel(16, 12, 404, 500, "(a) 새 약속을 저장할지 정한다")
    f.panel(432, 12, 312, 500, "(b) 열린 약속이 닫힌다")
    a = f.box(140, 44, "AGENDA 판단의 약속", "설명 @기한 (근거: 입력 구절)", kind="io", center=True)
    g1 = f.gate(140, 132, "사용자 입력에서 나왔나", "글자 겹침 검사", center=True)
    gc = f.gate(140, 220, "닫으라고 한 약속이 아닌가", center=True, h=50)
    g2 = f.gate(140, 300, "열린 약속과 같은가", "글자 규칙, 임베딩 0.85", center=True)
    d1 = f.box(298, g1.cy - 29, "버림", "입력에 근거 없음", kind="deny", w=112)
    dc = f.box(298, gc.cy - 29, "열지 않음", "닫는 말과 같음", kind="deny", w=112)
    d2 = f.box(298, g2.cy - 22, "기한만 갱신", kind="muted", w=112)
    for x, y in ((a, g1), (g1, gc), (gc, g2)):
        lbl = "예" if x is not a else ""
        f.edge([x.bottom, y.top], "accent", lbl, at=(x.cx + 8, (x.y2 + y.y) / 2 + 5), anchor="start", dy=0)
    f.edge([g1.right, d1.left], "deny", "아니오", at=((g1.x2 + d1.x) / 2, g1.cy))
    f.edge([gc.right, dc.left], "deny", "아니오", at=((gc.x2 + dc.x) / 2, gc.cy))
    f.edge([g2.right, d2.left], "", "같음", at=((g2.x2 + d2.x) / 2, g2.cy))
    s = f.store(588, 372, "열린 약속", "open", code=True, w=236, center=True)
    f.edge(
        [g2.bottom, (g2.cx, s.cy), s.left],
        "accent",
        "아니오, 새로 저장",
        at=(g2.cx + 8, s.cy - 8),
        anchor="start",
        dy=0,
    )
    hb = f.box(28, 444, "housing_budget 마감 약속", "게이트 없이, 사용자 대화 세션만", w=230)
    f.edge([hb.right, (s.cx, hb.cy), s.bottom], "")
    cols = [
        (490, "done", "closed_loops", "✓ 버튼"),
        (590, "dismissed", "거두는 말", "✕ 버튼"),
        (690, "expired", "기한 + 6시간", "기한 없이 7일"),
    ]
    for cx, title, why1, why2 in cols:
        b = f.box_lines(cx - 48, 48, 96, title, [why1, why2])
        f.edge([(cx, s.y + 1), b.bottom], "muted" if title == "expired" else "")
    f.text(588, 496, "↺ 닫힌 약속은 open 으로 되살린다", "pf-note", "middle")
    for i, g in enumerate((g1, gc, g2)):
        f.step(g, i + 1, gate=True)
    return f


def mcp() -> Fig:
    f = Fig("mcp", 330, "MCP 도구로 외부 이벤트를 성찰에 넣는 흐름")
    f.panel(16, 12, 728, 306, "")
    specs = [
        ("소스 정의", "external_sources/", True),
        ("Poller", "소스별 300초, 틱당 20건", False),
        ("MCP 도구 호출", "캘린더, 메일 같은 서버", False),
        ("이벤트 추출", "items, id, title 관례", False),
    ]
    ws = [f.need(t, s, c) + 4 for t, s, c in specs]
    xs = spread_x(ws, 28, 736)
    src = f.store(xs[0], 30, specs[0][0], specs[0][1], code=True, w=ws[0])
    poll = f.box(xs[1], 34, specs[1][0], specs[1][1], w=ws[1])
    srv = f.box(xs[2], 34, specs[2][0], specs[2][1], w=ws[2], kind="io")
    ext = f.box(xs[3], 34, specs[3][0], specs[3][1], w=ws[3])
    f.edge([src.right, poll.left], "")
    f.edge([poll.right, srv.left], "accent")
    f.edge([srv.right, ext.left], "accent")
    seen = f.gate(ext.cx, 148, "처음 보는 항목", "본 것은 7일 기억", center=True)
    f.edge([ext.bottom, seen.top], "accent")
    ib = f.store(srv.cx, 144, "inbox", "최대 200건", w=130, center=True)
    f.edge([seen.left, ib.right], "accent")
    tr = f.box(poll.cx, 148, "성찰 트리거", "넣은 뒤 Poller 가 깨운다", center=True)
    f.edge([poll.bottom, tr.top], "")
    th_w = f.need("다음 성찰", "inbox 를 한 번에 비운다") + 4
    th = f.box(max(28, src.cx - th_w / 2), 148, "다음 성찰", "inbox 를 한 번에 비운다", w=th_w, kind="accent")
    f.edge([tr.left, th.right], "")
    f.edge(
        [ib.bottom, (ib.cx, 236), (th.cx, 236), th.bottom], "accent", "drain", at=(ib.cx - 8, 230), anchor="end", dy=0
    )
    f.text(380, 270, "답을 기다리는 🔔 가 있으면 그 성찰은 inbox 를 건드리지 않는다", "pf-note", "middle")
    f.text(
        380,
        292,
        "이벤트는 말하라는 명령이 아니라 사실이다. 시급하고 사용자와 관련이 분명할 때만 🔔 로 말한다",
        "pf-note",
        "middle",
    )
    for i, b in enumerate((poll, srv, ext)):
        f.step(b, i + 1)
    f.step(seen, 4, gate=True)
    f.step(ib, 5)
    f.step(tr, 6)
    f.step(th, 7)
    return f


def scheduling() -> Fig:
    f = Fig("scheduling", 444, "스케줄 등록에서 전달까지")
    f.panel(16, 12, 728, 420, "")
    tool = f.box(24, 30, "schedule 도구", "대화 중 요청", w=140, kind="io")
    inp = f.box(24, 110, "/schedule", "문장 하나", w=140, kind="io")
    own = f.box(24, 196, "직접 쓴 파일", "cron, tool 작업", w=140, kind="io")
    f.edge([tool.bottom, inp.top], "")
    once = f.box(194, 66, "한 번", "…에, reminder 또는 task", w=176)
    until = f.box(194, 146, "마감까지 반복", "…까지, 남은 시간으로 주기", w=176)
    for k in (once, until):
        f.edge([inp.right, (180, inp.cy), (180, k.cy), k.left], "")
    yml = f.store(398, 127, "작업 파일", "schedules/*.yaml", code=True, w=142)
    for k in (once, until, own):
        f.edge([k.right, (384, k.cy), (384, yml.cy)], "", head=False)
    f.edge([(384, yml.cy), yml.left], "")
    kinds = [
        "10초마다 깨어남",
        "reminder: 문장 그대로",
        "task: 새 세션, 승인 없이",
        "tool: 도구를 바로",
        "goal: 목표 한 차례",
        "마감 지난 반복은 끄고 저장",
    ]
    sv = f.box_lines(564, 30, 172, "SchedulerService", kinds, kind="accent")
    f.edge([yml.right, (sv.x, yml.cy)], "accent")
    conv = f.box(404, 240, "에이전트의 말로", "deliver: conversation", code=True, w=180)
    f.edge([(612, sv.y2), (612, conv.cy), conv.right], "accent")
    f.edge([(712, sv.y2), (712, 322)], "accent", "notice", at=(706, 312), anchor="end", dy=0, head=False)
    f.edge([conv.bottom, (conv.cx, 322)], "", "못 건네면", at=(conv.cx + 8, 316), anchor="start", dy=0, head=False)
    outs = [
        ("열린 Web 연결 전부", "reminder 이벤트"),
        ("놓친 알림 20건", "열린 연결이 없을 때"),
        ("Web Push, Slack, Discord", "설정돼 있으면"),
    ]
    ws = [f.need(t, s) + 4 for t, s in outs]
    ob = [f.box(x, 340, t, s, w=w) for (t, s), x, w in zip(outs, spread_x(ws, 28, 736), ws, strict=True)]
    f.edge([(712, 322), (ob[0].cx, 322)], "accent", head=False)
    for b in ob:
        f.edge([(b.cx, 322), b.top], "accent")
    f.text(380, 420, "task 와 goal 은 승인 없이 돌고, 물어야 하는 도구(boundaries.ask)는 빠진다", "pf-note", "middle")
    f.step(inp, 1)
    f.step(yml, 2)
    f.step(sv, 3)
    f.step(conv, 4)
    return f


def voice() -> Fig:
    f = Fig("voice", 472, "음성 입력과 출력, Full-voice 루프, 음성 승인 해석")
    f.panel(16, 12, 728, 186, "(a) 듣고 말하는 길")
    specs = [
        ("마이크", "", False),
        ("STT", "Web Speech, faster-whisper", False),
        ("user_message", "", True),
        ("JARVIS", "", False),
    ]
    ws = [f.need(t, s, tcode=tc) + 4 for t, s, tc in specs]
    ws[0], ws[3] = 72, 88
    xs = spread_x(ws, 28, 560)
    kinds = ["io", "", "", "accent"]
    mic, stt, msg, ag = (
        f.box(x, 46, t, s, w=w, h=58, kind=k, tcode=tc)
        for (t, s, tc), x, w, k in zip(specs, xs, ws, kinds, strict=True)
    )
    for a, b in ((mic, stt), (stt, msg), (msg, ag)):
        f.edge([a.right, b.left], "accent")
    specs2 = [
        ("스피커", "", False),
        ("TTS", "브라우저, supertonic, 영어는 Piper, qwen", False),
        ("영어로 옮기기", "speak_english", True),
        ("읽을 글로", "기호 지우기, 금액은 한글", False),
    ]
    ws = [f.need(t, s, code=c) + 4 for t, s, c in specs2]
    ws[0] = 80
    xs = spread_x(ws, 28, 736)
    spk, tts, en, st = (
        f.box(x, 126, t, s, w=w, h=58, kind="io" if i == 0 else "", code=c)
        for i, ((t, s, c), x, w) in enumerate(zip(specs2, xs, ws, strict=True))
    )
    f.edge(
        [ag.right, (st.cx, ag.cy), st.top],
        "accent",
        "응답, 승인 질문, 🔔",
        at=(ag.x2 + 10, ag.cy - 8),
        anchor="start",
        dy=0,
    )
    for a, b in ((st, en), (en, tts), (tts, spk)):
        f.edge([a.left, b.right], "accent")
    f.panel(16, 210, 300, 250, "(b) Full-voice 루프")
    L = f.box(36, 252, "listening", w=100, kind="accent")
    P = f.box(186, 252, "processing", w=110)
    T = f.box(186, 372, "thinking", w=110)
    S = f.box(36, 372, "speaking", w=100)
    f.edge([L.right, P.left], "", "전사")
    f.edge([P.bottom, T.top], "", "user_message", at=(P.cx - 8, 344), anchor="end", dy=0)
    f.edge([T.left, S.right], "", "응답, 승인 질문", at=((T.x + S.x2) / 2, T.y2 + 22), dy=0)
    f.edge([S.top, L.bottom], "", "다 읽음", at=(S.cx - 8, 344), anchor="end", dy=0)
    f.panel(328, 210, 416, 250, "(c) 음성 승인 답은 애매하면 거부")
    rules = [
        ("부정어", "거부, 아니, 하지 마, 취소", "거부", "deny"),
        ("항상 키워드", "패턴 제안이 있을 때", "항상 허용", ""),
        ("허용 키워드", "네, 응 단독 포함", "허용", ""),
        ("그 밖", "사고 모델이 분류", "그 답, 애매하면 거부", ""),
    ]
    for i, (t, sub, out, kind) in enumerate(rules):
        y = 244 + i * 52
        b = f.box(370, y, t, sub, w=180, h=46)
        o = f.box(574, y + 5, out, w=160, h=36, kind=kind)
        f.edge([b.right, o.left], "deny" if kind else "accent")
        f.badge(352, y + 23, i + 1)
    return f


def team() -> Fig:
    f = Fig("multi-agent-orchestration", 398, "최상위 에이전트가 따로 갖는 것과 공유하는 것")
    f.panel(16, 12, 728, 374, "")
    J = f.box(26, 34, "J.A.R.V.I.S.", "id main, 팀 총괄", w=220, kind="jarvis")
    K = f.box(514, 34, "K.A.R.E.N.", "id karen, 정보 수집", w=220, kind="karen")
    f.edge([(J.x2, J.cy - 9), (K.x, K.cy - 9)], "accent", "ask_agent", at=(380, J.cy - 15))
    f.edge([(K.x, K.cy + 11), (J.x2, J.cy + 11)], "", "되묻기, A → B → A 까지", at=(380, J.cy + 30), dy=0)
    own = [
        "세션",
        "일화 기억, 작업 패턴",
        "목표, 약속(open loop)",
        "승인 규칙 approvals/<id>.yaml",
        "경계 boundaries ask, never",
        "모델, 도구, proactive 여부",
        "메인 색",
    ]
    f.box_lines(26, 124, 220, "따로 갖는 것", own, line_h=22)
    f.box_lines(514, 124, 220, "따로 갖는 것", own, line_h=22)
    sh = ["사용자 모델", "사용자에 대한 사실 (semantic)", "공용 승인 approvals.yaml", "AGENDA (에이전트 라벨)"]
    f.text(380, 150, "함께 쓰는 것", "pf-t", "middle")
    for i, t in enumerate(sh):
        f.box(380, 162 + i * 42, t, w=226, h=34, center=True, kind="accent")
    f.text(380, 354, "받는 쪽은 에이전트 쌍마다 세션 하나 (peer-main-karen) 에서 답한다", "pf-note", "middle")
    f.text(380, 374, "받은 일을 그 일을 보낸 에이전트에게 되돌리는 요청은 거절한다", "pf-note", "middle")
    return f


def orchestration_pattern() -> Fig:
    f = Fig("orchestration-pattern", 448, "서브 에이전트 오케스트레이션 패턴 네 가지")
    W2, H2 = 358, 206
    panels = [
        (16, 12, "(a) supervisor"),
        (386, 12, "(b) hierarchical"),
        (16, 230, "(c) market"),
        (386, 230, "(d) blackboard"),
    ]
    for x, y, lab in panels:
        f.panel(x, y, W2, H2, lab)
    sv = f.box(195, 44, "감독자 LLM", "agent_* 도구를 든다", center=True, kind="accent")
    a1 = f.box(120, 136, "agent a", w=96, h=36, center=True)
    a2 = f.box(270, 136, "agent b", w=96, h=36, center=True)
    f.edge([(sv.cx - 30, sv.y2), a1.top], "")
    f.edge([(sv.cx + 30, sv.y2), a2.top], "")
    f.text(195, 200, "LLM 이 도구 호출로 맡길 에이전트를 고른다", "pf-note", "middle")
    for i, (lab, names) in enumerate([("level 0", ["a", "b"]), ("level 1", ["c"]), ("level 2", ["d"])]):
        cx = 450 + i * 115
        f.text(cx, 62, lab, "pf-code", "middle")
        for j, n in enumerate(names):
            f.box(cx, 76 + j * 48 + (24 if len(names) == 1 else 0), f"agent {n}", w=84, h=36, center=True)
        if i:
            f.edge([(cx - 115 + 44, 118), (cx - 44, 118)], "accent")
    f.text(565, 200, "같은 레벨은 병렬, 앞 결과가 뒤로 간다", "pf-note", "middle")
    tk = f.box(34, 292, "task", w=70, h=36, kind="io")
    bids = [("a", "겹침 1"), ("b", "겹침 3"), ("c", "0, 입찰 안 함")]
    for i, (n, sc) in enumerate(bids):
        b = f.box(152, 258 + i * 44, f"agent {n}", w=92, h=34, kind="accent" if n == "b" else "")
        f.edge([tk.right, (b.x, b.cy)], "muted" if sc.startswith("0") else "")
        f.text(b.x2 + 10, b.cy + 4.5, sc, "pf-s")
    f.text(195, 418, "작업 낱말과 가장 많이 겹치는 하나가 맡는다", "pf-note", "middle")
    bb = f.store(565, 262, "공유 보드", "오케스트레이터가 쓴다", w=180, center=True)
    for i, n in enumerate(["a", "b", "c"]):
        b = f.box(450 + i * 115, 350, f"agent {n}", w=90, h=34, center=True)
        f.edge([(bb.cx - 24 + i * 24, bb.y2), b.top], "")
    f.text(565, 418, "스냅샷을 받아 병렬로 돌고, 결과는 보드에 모인다", "pf-note", "middle")
    return f


def focus_mode() -> Fig:
    f = Fig("focus-mode", 396, "Focus 모드의 한 턴과 화면 배치")
    f.panel(16, 12, 504, 372, "(a) Focus 동안의 한 턴")
    an = f.box(250, 50, "분석", "응답과 같이, 다섯 항목", w=156, center=True)
    ref = f.box(432, 50, "조사", "시작, 검색어가 나올 때", w=152, center=True)
    user = f.box(28, 160, "사용자 지시", w=104, h=58, kind="io")
    main = f.box(250, 160, "JARVIS", "오케스트레이터", w=156, center=True, kind="accent")
    log = f.box(250, 274, "기록", "턴 뒤, 3인칭 서기", w=156, center=True)
    prog = f.box(432, 274, "진행", "턴 뒤, 단계 완료", w=152, center=True)
    f.edge([user.right, main.left], "accent")
    f.edge([user.top, (user.cx, an.cy), an.left], "", "같이 시작", at=(user.cx + 8, an.cy - 8), anchor="start", dy=0)
    f.edge([an.right, ref.left], "")
    f.edge([an.bottom, main.top], "accent", "다음 턴의 Focus 맥락", at=(an.cx + 8, 136), anchor="start", dy=0)
    f.edge(
        [ref.bottom, (ref.cx, main.y + 14), (main.x2, main.y + 14)],
        "accent",
        "조사 요약",
        at=(ref.cx - 8, main.y + 6),
        anchor="end",
        dy=0,
    )
    f.edge([main.bottom, log.top], "", "응답 뒤", at=(main.cx + 8, 252), anchor="start", dy=0)
    f.edge([(main.x2, main.y2 - 14), (prog.cx, main.y2 - 14), prog.top], "")
    f.text(268, 354, "sub-agent 넷은 작업 동안 각자 세션을 유지한다", "pf-note", "middle")
    f.text(268, 373, "결과는 ~/.jarvis/focus/<task_id>/ 에 남는다", "pf-note", "middle")
    f.panel(532, 12, 212, 372, "(b) 화면")
    for i in range(3):
        f.chip(542, 46 + i * 92, "", w=10, h=84)
    f.chip(722, 46, "", w=10, h=60)
    f.chip(722, 114, "", w=10, h=200, kind="accent")
    for x, y, t in [(560, 46, "조사"), (640, 46, "분석"), (560, 190, "기록"), (640, 190, "진행")]:
        f.box(x, y, t, w=74, h=124)
    f.parts.append('<circle class="pf-box pf-box--accent" cx="637" cy="180" r="40"/>')
    f.text(637, 185, "구체 70%", "pf-t", "middle")
    f.text(638, 346, "좌우 카드는 세로 띠로 접힌다", "pf-note", "middle")
    f.text(638, 366, "Conversation 띠만 눌러 펼친다", "pf-note", "middle")
    return f


def extension() -> Fig:
    f = Fig("extension", 510, "~/.jarvis 아래 파일이 기동 때 붙는 자리")
    f.panel(16, 12, 240, 486, "(a) 놓는 파일")
    files = [
        ("tools/", "*.py, *.yaml"),
        ("mcp_servers", "설정 목록"),
        ("procedures/", "승인된 절차"),
        ("skills/", "*.md, *.yaml"),
        ("agents/", "*.yaml"),
        ("team/", "*.yaml"),
        ("external_sources/", "*.yaml"),
        ("plugins/", "훅 클래스"),
    ]
    fb = [f.box(32, 46 + i * 56, t, sub, w=208, h=46, kind="io") for i, (t, sub) in enumerate(files)]
    f.panel(268, 12, 476, 486, "(b) 붙는 자리. 파일을 더했으면 재시작한다")
    reg = f.box(300, 70, "도구 레지스트리", "승인한 절차는 다음 턴부터", w=212, h=54)
    sl = f.box(300, 186, "슬래시 커맨드", "/name 이 프롬프트로 펼쳐짐", w=212, h=54)
    ma = f.box(300, fb[4].y, "서브 에이전트 도구", "agent_<name>, orchestrate", code=True, w=212, h=46)
    top = f.box(300, fb[5].y, "최상위 에이전트", "자기 세션, ask_agent", w=212, h=46)
    ext = f.box(300, fb[6].y, "외부 이벤트 Poller", "성찰의 재료", w=212, h=46)
    f.edge([fb[0].right, (262, fb[0].cy), (262, reg.cy), reg.left], "accent")
    f.edge([fb[1].right, (262, fb[1].cy), (262, reg.cy)], "accent", head=False)
    f.edge([fb[2].right, (330, fb[2].cy), (330, reg.y2)], "accent")
    f.edge([(262, fb[2].cy), (262, sl.cy), sl.left], "accent")
    f.edge([fb[3].right, (262, fb[3].cy), (262, sl.cy)], "accent", head=False)
    for i, t in ((4, ma), (5, top), (6, ext)):
        f.edge([fb[i].right, t.left], "accent")
    hooks = [
        ("before_agent_start", True),
        ("LLM 응답", False),
        ("before_tool_call", True),
        ("도구 실행", False),
        ("after_tool_call", True),
        ("on_message_end", True),
    ]
    hb = []
    for i, (t, hook) in enumerate(hooks):
        hb.append(f.box(552, 36 + i * 54, t, w=176, h=38, kind="accent" if hook else "", tcode=hook))
    for a, b in zip(hb, hb[1:], strict=False):
        f.edge([a.bottom, b.top], "")
    f.text(640, 362, "강조한 네 칸이 플러그인 훅", "pf-note", "middle")
    f.edge([fb[7].right, (738, fb[7].cy), (738, hb[0].cy), hb[0].right], "accent")
    f.edge([reg.right, (536, reg.cy), (536, hb[3].cy), hb[3].left], "muted")
    return f


FIGURES = [
    architecture,
    inner_thought,
    proactive,
    memory,
    sessions,
    tools_and_approval,
    open_loop,
    mcp,
    scheduling,
    voice,
    team,
    orchestration_pattern,
    focus_mode,
    extension,
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for build in FIGURES:
        fig = build()
        if only and fig.name not in only:
            continue
        (OUT_DIR / f"{fig.name}.svg").write_text(fig.svg())
        print(OUT_DIR / f"{fig.name}.svg")


if __name__ == "__main__":
    main()
