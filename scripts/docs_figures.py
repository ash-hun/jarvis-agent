"""Generates the paper-style figures at the top of each docs feature page as SVG files under website/src/figures/."""

import sys
from pathlib import Path
from dataclasses import dataclass, field

OUT_DIR = Path(__file__).resolve().parent.parent / "website" / "src" / "figures"
WIDTH = 760
TITLE_FS = 13
SUB_FS = 11
CODE_FS = 10.5
PAD_X = 12
BOX_H = 40
BOX_H_SUB = 50


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


@dataclass
class Fig:
    name: str
    height: float
    label: str
    parts: list[str] = field(default_factory=list)

    # ── 도형 ──
    def panel(self, x, y, w, h, label="", bottom=False):
        self.parts.append(f'<rect class="pf-panel" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>')
        if label:
            self.parts.append(
                f'<text class="pf-plabel" x="{x + 12}" y="{y + h - 10 if bottom else y + 20}">{esc(label)}</text>'
            )

    def _size(self, title, sub, code, w, h):
        sub_mono = code
        need = max(
            text_width(title, TITLE_FS), text_width(sub, CODE_FS if sub_mono else SUB_FS, sub_mono) if sub else 0
        )
        return (w or round(need + 2 * PAD_X + 4), h or (BOX_H_SUB if sub else BOX_H))

    def _labels(self, cx, cy, title, sub, code, title_cls="pf-t"):
        if sub:
            self.parts.append(
                f'<text class="{title_cls}" x="{cx}" y="{cy - 4}" text-anchor="middle">{esc(title)}</text>'
            )
            cls = "pf-code" if code else "pf-s"
            self.parts.append(f'<text class="{cls}" x="{cx}" y="{cy + 13}" text-anchor="middle">{esc(sub)}</text>')
        else:
            self.parts.append(
                f'<text class="{title_cls}" x="{cx}" y="{cy + 4.5}" text-anchor="middle">{esc(title)}</text>'
            )

    def box(self, x, y, title, sub="", kind="", code=False, w=None, h=None, center=False) -> Box:
        w, h = self._size(title, sub, code, w, h)
        if center:
            x -= w / 2
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        self._labels(x + w / 2, y + h / 2, title, sub, code, "pf-t pf-t--" + kind if kind else "pf-t")
        return Box(x, y, w, h)

    def gate(self, x, y, title, sub="", code=False, w=None, h=None, center=False) -> Box:
        w, h = self._size(title, sub, code, w, h)
        w += 16
        if center:
            x -= w / 2
        self.parts.append(f'<rect class="pf-gate" x="{x:.1f}" y="{y}" width="{w}" height="{h}" rx="{h / 2}"/>')
        self._labels(x + w / 2, y + h / 2, title, sub, code)
        return Box(x, y, w, h)

    def store(self, x, y, title, sub="", code=False, w=None, h=None, center=False) -> Box:
        w, h = self._size(title, sub, code, w, h)
        h += 8
        if center:
            x -= w / 2
        e = 5
        self.parts.append(
            f'<path class="pf-store" d="M{x:.1f},{y + e} a{w / 2:.1f},{e} 0 0,0 {w},0 a{w / 2:.1f},{e} 0 0,0 {-w},0 '
            f'v{h - 2 * e} a{w / 2:.1f},{e} 0 0,0 {w},0 v{-(h - 2 * e)}"/>'
        )
        self._labels(x + w / 2, y + h / 2 + 3, title, sub, code)
        return Box(x, y, w, h)

    def badge(self, x, y, n):
        self.parts.append(f'<circle class="pf-badge" cx="{x}" cy="{y}" r="8.5"/>')
        self.parts.append(f'<text class="pf-badge-t" x="{x}" y="{y + 3.6}" text-anchor="middle">{n}</text>')

    def text(self, x, y, s, cls="pf-s", anchor="start"):
        self.parts.append(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{esc(s)}</text>')

    def vtext(self, x, y, s, cls="pf-s"):
        self.parts.append(
            f'<text class="{cls}" x="{x}" y="{y}" text-anchor="middle" transform="rotate(-90 {x} {y})">{esc(s)}</text>'
        )

    def box_lines(self, x, y, w, title, lines, kind="", code=False, line_h=16) -> Box:
        h = 34 + line_h * len(lines)
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
        self.text(x + w / 2, y + 21, title, "pf-t", "middle")
        for i, line in enumerate(lines):
            self.text(x + w / 2, y + 40 + i * line_h, line, "pf-code" if code else "pf-s", "middle")
        return Box(x, y, w, h)

    def chip(self, x, y, s, kind="", w=24, h=20) -> Box:
        cls = "pf-box" + (f" pf-box--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="4"/>')
        self.text(x + w / 2, y + h / 2 + 4, s, "pf-chip", "middle")
        return Box(x, y, w, h)

    def bar(self, x, y, w, s, kind="", h=18):
        cls = "pf-bar" + (f" pf-bar--{kind}" if kind else "")
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>')
        if s:
            self.text(x + w / 2, y + h / 2 + 4, s, "pf-bar-t" + (f" pf-bar-t--{kind}" if kind else ""), "middle")

    def edge(self, pts, kind="", label="", at=None, anchor="middle", dy=-5, head=True):
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        cls = "pf-edge" + (f" pf-edge--{kind}" if kind else "")
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

    def svg(self) -> str:
        heads = "".join(
            f'<marker id="{self.name}-h{suffix}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" '
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
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {self.height}" class="pf-svg" '
            f'role="img" aria-label="{esc(self.label)}">\n<defs>{heads}</defs>\n{body}\n</svg>\n'
        )


# ── 그림 ──


def open_loop() -> Fig:
    f = Fig("open-loop", 352, "Open Loop 의 저장과 닫힘")
    f.panel(16, 12, 420, 328, "(a) 새 약속을 저장할지 정한다")
    f.panel(450, 12, 294, 328, "(b) 열린 약속이 닫힌다")
    a = f.box(150, 44, "사고 프레임의 약속", "설명 @기한 (근거: 입력 구절)", kind="io", center=True)
    g1 = f.gate(150, 124, "사용자 입력에서 나왔나", "근거 50% 또는 문구 20% 글자 겹침", center=True)
    g2 = f.gate(150, 204, "열린 약속과 같은가", "정규화, 포함, 임베딩 0.85, Jaccard 0.4", center=True)
    d1 = f.box(362, 124, "버림", "기억에서 옮김", kind="deny", center=True, w=110)
    d2 = f.box(362, 204, "기한만 갱신", "바뀔 게 없으면 그대로", kind="muted", center=True, w=130)
    f.edge([a.bottom, g1.top], "accent")
    f.edge(
        [g1.bottom, g2.top], "accent", "예", at=(g1.cx + 8, (g1.bottom[1] + g2.top[1]) / 2 + 4), anchor="start", dy=0
    )
    f.edge([g1.right, d1.left], "deny", "아니오")
    f.edge([g2.right, d2.left], "", "같음")
    s = f.store(597, 270, "열린 약속", "open", code=True, w=270, center=True)
    f.edge(
        [g2.bottom, (g2.cx, s.cy), s.left],
        "accent",
        "아니오, 새로 저장",
        at=(g2.cx + 8, s.cy - 6),
        anchor="start",
        dy=0,
    )
    cols = [
        (507, "done", "closed_loops", "✓ 버튼"),
        (597, "dismissed", "거두는 말", "✕ 버튼"),
        (687, "expired", "기한 + 6시간", "기한 없이 7일"),
    ]
    for cx, title, why1, why2 in cols:
        b = f.box(cx, 50, title, w=84, center=True)
        f.edge([(cx, s.y + 1), b.bottom], "muted" if title == "expired" else "")
        f.text(cx, 158, why1, "pf-elabel", "middle")
        f.text(cx, 173, why2, "pf-elabel", "middle")
    return f


def architecture() -> Fig:
    f = Fig("architecture", 372, "JARVIS 의 계층 구조")
    rows = [
        ("ui/  화면", "TUI (Textual), Web HUD. 같은 AppAssembly 를 받아 화면만 다르다"),
        ("app/  조립", "InfraBuilder 가 설정 하나로 도구, 메모리, 저장소, 보안을 만든다"),
        ("core/  오케스트레이션과 정책", "AgentSession, 보안 파이프라인, 도구, 승인, proactive, 스케줄러"),
        ("agent_layer/  에이전트 런타임", "에이전트 루프, 내적 사고 엔진, 메모리 미들웨어, 세션 저장소"),
        ("model_layer/  LLM 추상화", "프로바이더마다 stream() 하나, 임베딩"),
    ]
    f.panel(16, 12, 728, 348, "")
    boxes = []
    for i, (t, sub) in enumerate(rows):
        b = f.box(70, 30 + i * 66, t, sub, w=470, kind="accent" if i == 2 else "")
        boxes.append(b)
    for up, down in zip(boxes, boxes[1:], strict=False):
        f.edge([up.bottom, down.top], "")
    f.edge([(40, 40), (40, 340)], "accent")
    f.vtext(32, 190, "의존 방향. 아래층은 위층을 모른다", "pf-elabel")
    mem = f.box(560, 162, "memory/", "작업 기억, 장기 기억", w=168, h=118)
    f.edge([boxes[2].right, (mem.x, boxes[2].cy)], "")
    f.edge([boxes[3].right, (mem.x, boxes[3].cy)], "")
    f.box(560, 30, "common/", "로거. 어느 층이든 쓴다", w=168, kind="muted")
    f.box(560, 294, "프로바이더", "anthropic, openai, gemini 외 2", w=168, kind="muted", h=50)
    f.edge([boxes[4].right, (560, boxes[4].cy)], "muted", head=False)
    return f


def inner_thought() -> Fig:
    f = Fig("inner-thought", 440, "내적 사고 한 번의 흐름과 시점")
    f.panel(16, 12, 728, 270, "(a) 사고 한 번")
    ins = ["사용자 입력", "열린 약속", "사용자 모델", "회상한 기억 5건", "최근 대화 8턴"]
    ib = [f.box(96, 44 + i * 44, t, w=128, h=34, center=True, kind="io" if i == 0 else "") for i, t in enumerate(ins)]
    r = f.box(246, 132, "템플릿 렌더", "inner_thought.md", code=True, w=118, center=True)
    for b in ib:
        f.edge([b.right, (172, b.cy), (172, r.cy), r.left], "", head=False)
    f.edge([(172, r.cy), r.left], "")
    m = f.box(378, 132, "사고 모델 호출", "도구 없음, JSON 강제", w=118, center=True, kind="accent")
    f.edge([r.right, m.left], "accent")
    fr = f.box_lines(
        452,
        74,
        120,
        "ThoughtFrame",
        ["decision", "confidence", "utterance", "needs_background", "open_loops", "closed_loops"],
        code=True,
    )
    f.edge([m.right, (fr.x, m.cy)], "accent")
    outs = [
        ("💭 한 줄", "결정과 확신도"),
        ("시스템 프롬프트", "[내적 사고] 블록"),
        ("Dual channel", "filler 먼저"),
        ("약속 저장과 닫기", "요청 모드만"),
    ]
    ob = [f.box(662, 40 + i * 58, t, sub, w=140, h=46, center=True) for i, (t, sub) in enumerate(outs)]
    for b in ob:
        f.edge([(fr.x + fr.w, fr.cy), (586, fr.cy), (586, b.cy), b.left], "")
    f.panel(16, 294, 728, 134, "(b) 사고와 메인 응답의 순서 (JARVIS_THOUGHT__REQUEST_TIMING)")
    rows = [("before", (0, 90), (90, 210)), ("race", (0, 90), (27, 210)), ("after", (120, 210), (0, 120))]
    x0, scale = 170, 2.2
    for i, (name, think, main) in enumerate(rows):
        y = 322 + i * 38
        f.text(150, y + 18, name, "pf-code", "end")
        f.bar(x0 + think[0] * scale, y, (think[1] - think[0]) * scale, "사고", "accent", h=15)
        f.bar(x0 + main[0] * scale, y + 17, (main[1] - main[0]) * scale, "메인 응답", h=15)
    f.text(x0 + 27 * scale - 5, 322 + 38 + 28, "3초", "pf-note", "end")
    return f


def spread(f: Fig, specs: list[tuple], y: float, x0: float, x1: float, reverse: bool = False) -> list[Box]:
    """(종류, 제목, 부제, code, w) 를 x0~x1 에 같은 간격으로 놓는다. reverse 면 오른쪽에서 왼쪽으로 읽힌다."""
    widths = [f._size(t, sub, code, w, None)[0] + (16 if kind == "gate" else 0) for kind, t, sub, code, w, *_ in specs]
    gap = (x1 - x0 - sum(widths)) / max(1, len(specs) - 1)
    order = list(zip(specs, widths, strict=True))
    xs, x = [], x0
    for _, w in order[::-1] if reverse else order:
        xs.append(x)
        x += w + gap
    if reverse:
        xs = xs[::-1]
    boxes = []
    for (kind, t, sub, code, w, *extra), bx in zip(specs, xs, strict=True):
        if kind == "gate":
            boxes.append(f.gate(bx, y, t, sub, code=code))
        else:
            boxes.append(f.box(bx, y, t, sub, code=code, w=w, kind=extra[0] if extra else ""))
    return boxes


def proactive() -> Fig:
    f = Fig("proactive", 472, "먼저 말하기 전에 지나는 게이트와 피드백 학습")
    f.panel(16, 12, 728, 270, "(a) 성찰 한 번")
    # 위 줄은 사고 앞뒤의 거르기(session.reflect), 아래 줄은 정책 게이트와 보내기 직전 검사. 코드 순서 그대로다
    t, g1, g2, th, g3 = spread(f, [
        ("box", "트리거", "주기, 유휴, 이벤트", False, 104, "io"),
        ("gate", "답 기다리는 🔔 없음", "", False, None),
        ("gate", "대화가 있었음", "", False, None),
        ("box", "성찰 사고", "+ decision model", False, 118),
        ("gate", "되풀이 아님", "최근 🔔, 10분 안 답", False, None),
    ], 40, 28, 718)
    for a, b in ((t, g1), (g1, g2), (g2, th), (th, g3)):
        f.edge([a.right, b.left], "accent")
    g4, g5, g6, g7, g8 = spread(f, [
        ("gate", "act 또는 ask", "decision", True, None),
        ("gate", "확신도 ≥ θ", "기본 0.6", False, None),
        ("gate", "말할 문장 있음", "utterance", True, None),
        ("gate", "쿨다운 지남", "세션별 300초", False, None),
        ("gate", "답하는 중 아님", "busy", True, None),
    ], 156, 28, 718, reverse=True)
    f.edge([g3.right, (732, g3.cy), (732, g4.cy), g4.right], "accent")
    for a, b in ((g4, g5), (g5, g6), (g6, g7), (g7, g8)):
        f.edge([a.left, b.right], "accent")
    out = f.box(28, 222, "🔔 먼저 건네는 말", "저위험 자율 행동 결과 포함", kind="accent", w=170)
    f.edge([g8.bottom, (g8.cx, out.y)], "accent")
    lane = f.box(40, 116, "침묵. 이유만 로그에 남긴다", w=666, h=26, kind="muted")
    for g in (g1, g2, g3):
        f.edge([g.bottom, (g.cx, lane.y)], "muted", head=True)
    for g in (g4, g5, g6, g7, g8):
        f.edge([g.top, (g.cx, lane.y + lane.h)], "muted", head=True)
    f.text(th.cx, th.y + th.h + 14, "알릴 것이 없으면 문장을 비운다", "pf-s", "middle")
    f.panel(274, 294, 470, 166, "(b) 피드백 학습")
    react = f.box(340, 348, "🔔 에 대한 반응", "다음 짧은 답", w=118, center=True, kind="io")
    opts = ["수락, θ − 0.05", "무시, θ + 0.05", "무응답 600초, θ + 0.025"]
    ob = [f.box(502, 318 + i * 44, t, w=170, h=34, center=True) for i, t in enumerate(opts)]
    for b in ob:
        f.edge([react.right, (407, react.cy), (407, b.cy), b.left], "", head=True)
    th_box = f.box(670, 348, "임계치 θ", "0.3 ~ 0.95", w=110, center=True, kind="accent")
    for b in ob:
        f.edge([b.right, (608, b.cy), (608, th_box.cy), th_box.left], "", head=False)
    f.edge([(608, th_box.cy), th_box.left], "")
    f.edge(
        [th_box.top, (th_box.cx, 290), (g5.cx, 290), g5.bottom],
        "accent", "θ 를 옮긴다", at=(g5.cx + 6, 268), anchor="start", dy=0,
    )
    f.panel(16, 294, 246, 166, "(c) Dual channel")
    g = f.gate(139, 324, "오래 걸릴 요청인가", "needs_background", code=True, center=True)
    fl = f.box(78, 404, "filler 먼저", "잠깐만요, 확인할게요", w=108, center=True, kind="accent")
    mn = f.box(200, 404, "메인 응답", "뒤에서 돈다", w=100, center=True)
    f.edge([(g.cx - 30, g.y + g.h), (fl.cx, fl.y)], "accent", "예", at=(g.cx - 52, 392), dy=0)
    f.edge([(g.cx + 30, g.y + g.h), (mn.cx, mn.y)], "")
    return f


def memory() -> Fig:
    f = Fig("memory", 392, "턴마다 기억을 읽는 길과 장기 기억에 쓰는 순간")
    f.panel(16, 12, 728, 236, "(a) 매 턴 읽기")
    h = f.box(84, 48, "세션 히스토리", w=116, h=50, center=True, kind="io")
    c = f.box(222, 48, "요약과 압축", "10만 자 넘으면 요약", w=128, center=True)
    w = f.box(364, 48, "창", "최근 50 메시지", w=112, center=True)
    pr = f.box_lines(
        452,
        36,
        168,
        "프롬프트",
        ["[핵심 사실] 3건", "[장기 기억] 회상 3건", "[절차 기억]", "[작업 패턴]", "요약 + 최근 메시지"],
    )
    llm = f.box(684, 92, "LLM", w=72, center=True, kind="accent")
    f.edge([h.right, c.left], "accent")
    f.edge([c.right, w.left], "accent")
    f.edge([w.right, (pr.x, w.cy)], "accent")
    f.edge([(pr.x + pr.w, llm.cy), llm.left], "accent")
    ltm = f.store(80, 168, "장기 기억", "의미 shared, 일화 private, 절차 private", w=420)
    f.edge(
        [ltm.right, (pr.cx, ltm.cy), (pr.cx, pr.y + pr.h)],
        "",
        "회상: 키워드 + 벡터, 점수",
        at=(pr.cx + 8, 176),
        anchor="start",
        dy=0,
    )
    f.panel(16, 260, 728, 120, "(b) 정해진 순간에만 쓴다. 매 턴 대화는 자동으로 쓰지 않는다", bottom=True)
    writes = [
        ("/remember", "의미, shared"),
        ("압축, 세션 종료", "일화, private"),
        ("통합", "일화에서 사실 뽑기"),
        ("remember_task_pattern", "절차, 에이전트별"),
    ]
    xs = [130, 270, 410, 610]
    for x, (t, sub) in zip(xs, writes, strict=True):
        b = f.box(x, 290, t, sub, center=True, w=max(124, round(text_width(t, TITLE_FS)) + 30))
        if x < ltm.x + ltm.w:
            f.edge([b.top, (x, ltm.y + ltm.h)], "")
        else:
            f.edge([b.top, (b.cx, 284), (480, 284), (480, ltm.y + ltm.h)], "")
    return f


def sessions() -> Fig:
    f = Fig("sessions", 330, "세션의 저장, 분기, 종료")
    f.panel(16, 12, 728, 176, "(a) 세션과 분기")
    f.text(32, 62, "세션 A", "pf-t")
    f.text(32, 77, "agent: main", "pf-code")
    seq = ["U", "A", "T", "A", "U", "A"]
    xa = [130 + i * 34 for i in range(len(seq))]
    for x, k in zip(xa, seq, strict=True):
        f.chip(x, 52, k, "accent" if k == "U" else "")
    f.edge([(xa[-1] + 30, 62), (430, 62)], "muted", head=False)
    end = f.box(430, 42, "종료", "TUI 종료, Web 셧다운", w=134)
    hooks = f.box(590, 42, "세션 요약", "일화 기억, 통합, 절차 학습", w=140)
    f.edge([end.right, hooks.left], "")
    f.text(32, 142, "세션 B", "pf-t")
    f.text(32, 157, "parent_id = A", "pf-code")
    for i in range(4):
        f.chip(130 + i * 34, 132, seq[i], "muted")
    for i, k in enumerate(["U", "A"]):
        f.chip(130 + (4 + i) * 34, 132, k, "accent" if k == "U" else "")
    f.edge(
        [(xa[3] + 12, 74), (xa[3] + 12, 100), (130 + 3 * 34 + 12, 100), (130 + 3 * 34 + 12, 130)],
        "accent",
        "/branch, ⑂",
        at=(xa[3] + 22, 104),
        anchor="start",
        dy=0,
    )
    f.text(400, 146, "메시지를 통째로 복사한다. 이후 변경은 서로 전파되지 않는다", "pf-s")
    f.panel(16, 200, 728, 118, "(b) 한 턴이 저장되는 때")
    u = f.box(100, 238, "사용자 메시지", "턴 시작 때 바로 저장", w=150, center=True, kind="io")
    lp = f.box(300, 238, "에이전트 루프", "LLM 과 도구, 최대 20턴", w=160, center=True)
    sv = f.box(510, 238, "나머지 메시지", "루프가 끝난 뒤 한꺼번에", w=170, center=True)
    st = f.store(672, 234, "저장소", "jsonl, Postgres", w=110, center=True)
    f.edge([u.right, lp.left], "accent")
    f.edge([lp.right, sv.left], "accent")
    f.edge([sv.right, st.left], "accent")
    f.edge([(u.cx, u.y + u.h), (u.cx, 294), (672, 294), (672, st.y + st.h)], "", head=True)
    f.text(300, 311, "루프 도중에 죽으면 사용자 메시지만 남는다", "pf-note", "middle")
    return f


def tools_and_approval() -> Fig:
    f = Fig("tools-and-approval", 352, "도구 호출 한 번이 지나는 검사와 승인")
    f.panel(16, 12, 728, 328, "")
    call = f.box(76, 36, "도구 호출", "LLM 이 고름", w=104, center=True, kind="io")
    g1 = f.gate(214, 36, "허용 목록", "정책", center=True)
    g2 = f.gate(356, 36, "플러그인", "before_tool_call", code=True, center=True)
    g3 = f.gate(512, 36, "승인이 필요한 도구", center=True, h=50)
    g4 = f.gate(668, 36, "규칙에 맞나", "공용, 에이전트별", center=True)
    for a, b in ((call, g1), (g1, g2), (g2, g3), (g3, g4)):
        f.edge([a.right, b.left], "accent")
    ex = f.box(430, 156, "실행", w=80, h=50, center=True, kind="accent")
    f.edge(
        [(g3.cx, g3.y + g3.h), (g3.cx, 128), (ex.cx + 14, 128), (ex.cx + 14, ex.y)],
        "accent",
        "아니오",
        at=(g3.cx + 6, 116),
        anchor="start",
        dy=0,
    )
    f.edge(
        [(g4.cx - 40, g4.y + g4.h), (g4.cx - 40, 128), (ex.cx + 14, 128)],
        "accent",
        "맞음",
        at=(g4.cx - 34, 116),
        anchor="start",
        dy=0,
        head=False,
    )
    ask = f.box(668, 156, "사람에게 묻기", "120초", center=True, w=120)
    f.edge([(g4.cx + 20, g4.y + g4.h), (g4.cx + 20, ask.y)], "", "아니오", at=(g4.cx + 26, 132), anchor="start", dy=0)
    f.edge([ask.left, ex.right], "accent", "ALLOW")
    rule = f.store(632, 236, "규칙 저장", "approvals/<agent>.yaml", code=True, w=168, center=True)
    f.edge([ask.bottom, (ask.cx, rule.y)], "", "ALWAYS", at=(ask.cx + 6, 226), anchor="start", dy=0)
    f.edge([rule.left, (ex.cx, rule.cy), (ex.cx, ex.y + ex.h)], "")
    after = f.box(276, 156, "after_tool_call", w=130, h=50, center=True)
    res = f.box(100, 156, "결과를 LLM 에", "도구 루프 최대 20턴", w=140, center=True)
    f.edge([ex.left, after.right], "accent")
    f.edge([after.left, res.right], "accent")
    lane = f.box(
        40, 296, "거부는 예외가 아니다. is_error 결과로 LLM 에 돌아가고 루프는 계속된다", w=530, h=30, kind="deny"
    )
    f.edge(
        [(g1.cx, g1.y + g1.h), (g1.cx, 108), (186, 108), (186, lane.y)],
        "deny",
        "없음",
        at=(g1.cx + 6, 98),
        anchor="start",
        dy=0,
    )
    f.edge(
        [(g2.cx, g2.y + g2.h), (g2.cx, 118), (356, 118), (356, lane.y)],
        "deny",
        "block",
        at=(g2.cx + 6, 112),
        anchor="start",
        dy=0,
    )
    f.edge(
        [ask.right, (738, ask.cy), (738, 334), (lane.x + lane.w - 40, 334), (lane.x + lane.w - 40, lane.y + lane.h)],
        "deny",
        "DENY, 시간 초과",
        at=(700, 330),
        anchor="end",
        dy=0,
    )
    f.edge([(res.cx, lane.y), (res.cx, res.y + res.h)], "deny")
    return f


def voice() -> Fig:
    f = Fig("voice", 416, "음성 입력과 출력, Full-voice 루프, 음성 승인 해석")
    f.panel(16, 12, 728, 142, "(a) 듣고 말하는 길")
    mic = f.box(70, 40, "마이크", w=76, h=44, center=True, kind="io")
    stt = f.box(214, 40, "STT", "Web Speech 또는 faster-whisper", w=190, h=44, center=True)
    msg = f.box(380, 40, "user_message", w=118, h=44, center=True)
    ag = f.box(520, 40, "JARVIS", w=88, h=44, center=True, kind="accent")
    for a, b in ((mic, stt), (stt, msg), (msg, ag)):
        f.edge([a.right, b.left], "accent")
    tts = f.box(380, 98, "TTS", "Web Speech, supertonic, 영어는 Piper", w=204, h=44, center=True)
    spk = f.box(214, 98, "스피커", w=76, h=44, center=True, kind="io")
    f.edge(
        [(ag.cx, ag.y + ag.h), (ag.cx, tts.cy), tts.right],
        "accent",
        "응답, 승인 질문, 🔔",
        at=(ag.cx + 8, tts.cy - 6),
        anchor="start",
        dy=0,
    )
    f.edge([tts.left, spk.right], "accent")
    f.text(735, 66, "브라우저가 기본, 서버는 설정으로", "pf-note", "end")
    f.panel(16, 166, 300, 238, "(b) Full-voice 루프")
    L = f.box(90, 208, "listening", w=96, center=True, kind="accent")
    P = f.box(242, 208, "processing", w=96, center=True)
    T = f.box(242, 330, "thinking", w=96, center=True)
    S = f.box(90, 330, "speaking", w=96, center=True)
    f.edge([L.right, P.left], "", "전사")
    f.edge([P.bottom, T.top], "", "user_message", at=(P.cx + 6, 282), anchor="start", dy=0)
    f.edge([T.left, S.right], "", "응답, 승인 질문", at=((T.x + S.x + S.w) / 2, T.cy + 22), dy=0)
    f.edge([S.top, L.bottom], "", "다 읽음", at=(S.cx - 6, 282), anchor="end", dy=0)
    f.panel(328, 166, 416, 238, "(c) 음성 승인 답은 애매하면 거부")
    rules = [
        ("부정어", "거부, 아니, 하지 마, 취소", "거부", "deny"),
        ("항상 키워드", "패턴 제안이 있을 때", "항상 허용", ""),
        ("허용 키워드", "네, 응 단독 포함", "허용", ""),
        ("그 밖", "사고 모델이 분류, 실패하면", "거부", "deny"),
    ]
    for i, (t, sub, out, kind) in enumerate(rules):
        y = 198 + i * 50
        b = f.box(372, y, t, sub, w=190, h=44)
        o = f.box(640, y + 5, out, w=96, h=34, kind=kind)
        f.edge([b.right, o.left], "deny" if kind else "accent")
        f.badge(354, y + 22, i + 1)
    return f


def scheduling() -> Fig:
    f = Fig("scheduling", 330, "스케줄 등록에서 전달까지")
    f.panel(16, 12, 728, 306, "")
    inp = f.box(76, 98, "/schedule", "문장 하나", w=100, center=True, kind="io")
    kinds = [
        ("한 번", "…에, LLM 이 reminder 또는 task 로 분류"),
        ("마감까지 반복", "…까지, 남은 시간으로 주기 선택"),
        ("cron", "0 9 * * * …"),
    ]
    kb = [f.box(256, 30 + i * 68, t, sub, w=214, center=True) for i, (t, sub) in enumerate(kinds)]
    for b in kb:
        f.edge([inp.right, (138, inp.cy), (138, b.cy), b.left], "")
    yml = f.store(458, 94, "작업 파일", "schedules/<name>.yaml", code=True, w=150, center=True)
    for b in kb:
        f.edge([b.right, (372, b.cy), (372, yml.cy)], "", head=False)
    f.edge([(372, yml.cy), (yml.x, yml.cy)], "")
    sv = f.box(640, 98, "SchedulerService", "10초마다 깨어남", w=140, center=True, kind="accent")
    f.edge([(yml.x + yml.w, sv.cy), sv.left], "accent")
    rem = f.box(568, 24, "reminder", "문장을 그대로 알림", w=128, center=True)
    task = f.box(686, 24, "task", "새 세션, 승인 없이", w=108, center=True)
    f.edge([(sv.cx - 30, sv.y), (rem.cx, rem.y + rem.h)], "accent")
    f.edge([(sv.cx + 30, sv.y), (task.cx, task.y + task.h)], "accent")
    outs = [
        (290, "열린 Web 연결 전부", "reminder 이벤트", 150),
        (474, "놓친 알림 20건", "다음 접속 때, 재시작하면 사라짐", 190),
        (640, "Slack", "웹훅이 있으면", 110),
    ]
    f.edge([(sv.cx, sv.y + sv.h), (sv.cx, 238)], "accent", head=False)
    for cx, t, sub, w in outs:
        b = f.box(cx, 256, t, sub, w=w, center=True)
        f.edge([(sv.cx, 238), (cx, 238), (cx, b.y)], "accent")
    return f


def mcp() -> Fig:
    f = Fig("mcp", 262, "MCP 도구로 외부 이벤트를 성찰에 넣는 흐름")
    f.panel(16, 12, 728, 238, "")
    src = f.store(100, 36, "소스 정의", "external_sources/", code=True, w=150, center=True)
    poll = f.box(262, 40, "Poller", "소스별 interval 300초", w=140, center=True)
    srv = f.box(430, 40, "MCP 도구 호출", "캘린더, 메일 같은 서버", w=150, center=True, kind="io")
    ext = f.box(616, 40, "이벤트 추출", "items, id, title 관례", w=150, center=True)
    f.edge([src.right, poll.left], "")
    f.edge([poll.right, srv.left], "accent")
    f.edge([srv.right, ext.left], "accent")
    seen = f.gate(616, 140, "처음 보는 항목", "본 것은 7일 기억", center=True)
    f.edge([ext.bottom, seen.top], "accent")
    ib = f.store(430, 136, "inbox", "최대 200건, 틱당 20건", w=150, center=True)
    f.edge([seen.left, (ib.x + ib.w, seen.cy)], "accent")
    tr = f.box(262, 140, "성찰 트리거", "새 이벤트가 깨운다", w=140, center=True)
    f.edge([ib.left, tr.right], "accent")
    th = f.box(96, 140, "다음 성찰", "inbox 를 한 번 비운다", w=150, center=True, kind="accent")
    f.edge([tr.left, th.right], "accent")
    f.text(
        380,
        232,
        "이벤트는 말하라는 명령이 아니라 사실이다. 시급하고 사용자와 관련이 분명할 때만 🔔 로 말한다",
        "pf-note",
        "middle",
    )
    return f


def team() -> Fig:
    f = Fig("multi-agent-orchestration", 360, "최상위 에이전트가 따로 갖는 것과 공유하는 것")
    f.panel(16, 12, 728, 336, "")
    J = f.box(124, 34, "J.A.R.V.I.S.", "id main, 팀 총괄", w=180, center=True, kind="jarvis")
    K = f.box(636, 34, "K.A.R.E.N.", "id karen, 정보 수집", w=180, center=True, kind="karen")
    f.edge([(J.x + J.w, J.cy - 8), (K.x, K.cy - 8)], "accent", "ask_agent", at=(380, J.cy - 14))
    f.edge([(K.x, K.cy + 10), (J.x + J.w, J.cy + 10)], "", "되묻기, A → B → A 까지", at=(380, J.cy + 24), dy=0)
    own = ["세션", "일화 기억, 작업 패턴", "승인 규칙 approvals/<id>.yaml", "모델, 도구, proactive 여부", "메인 색"]
    for i, t in enumerate(own):
        f.box(124, 104 + i * 46, t, w=196, h=36, center=True)
        f.box(636, 104 + i * 46, t, w=196, h=36, center=True)
    f.text(124, 98, "따로 갖는 것", "pf-elabel", "middle")
    f.text(636, 98, "따로 갖는 것", "pf-elabel", "middle")
    sh = ["사용자 모델", "사용자에 대한 사실 (semantic)", "공용 승인 approvals.yaml", "AGENDA (에이전트 라벨)"]
    f.text(380, 120, "함께 쓰는 것", "pf-elabel", "middle")
    for i, t in enumerate(sh):
        f.box(380, 128 + i * 50, t, w=208, h=38, center=True, kind="accent")
    f.text(380, 352 - 16, "받는 쪽은 에이전트 쌍마다 세션 하나 (peer-main-karen) 에서 답한다", "pf-note", "middle")
    return f


def orchestration_pattern() -> Fig:
    f = Fig("orchestration-pattern", 372, "서브 에이전트 오케스트레이션 패턴 네 가지")
    W2, H2 = 356, 168
    panels = [
        (16, 12, "(a) supervisor"),
        (388, 12, "(b) hierarchical"),
        (16, 192, "(c) market"),
        (388, 192, "(d) blackboard"),
    ]
    for x, y, lab in panels:
        f.panel(x, y, W2, H2, lab)
    sv = f.box(194, 44, "감독자 LLM", "agent_* 도구를 든다", w=150, center=True, kind="accent")
    a1 = f.box(120, 128, "agent a", w=90, h=34, center=True)
    a2 = f.box(268, 128, "agent b", w=90, h=34, center=True)
    f.edge([(sv.cx - 30, sv.y + sv.h), (a1.cx, a1.y)], "")
    f.text(194, 174, "LLM 이 도구 호출로 맡길 에이전트를 고른다", "pf-note", "middle")
    f.edge([(sv.cx + 30, sv.y + sv.h), (a2.cx, a2.y)], "")
    for i, (lab, names) in enumerate([("level 0", ["a", "b"]), ("level 1", ["c"]), ("level 2", ["d"])]):
        x = 430 + i * 110
        f.text(x + 30, 60, lab, "pf-code", "middle")
        for j, n in enumerate(names):
            f.box(x + 30, 72 + j * 44 + (22 if len(names) == 1 else 0), f"agent {n}", w=74, h=32, center=True)
        if i:
            f.edge([(x - 42, 110), (x - 6, 110)], "accent", head=True)
    f.text(570, 170, "같은 레벨은 병렬, 앞 결과가 뒤로 간다", "pf-note", "middle")
    tk = f.box(80, 248, "task", w=70, h=34, center=True, kind="io")
    bids = [("a", "0.4"), ("b", "0.9"), ("c", "0.2")]
    for i, (n, sc) in enumerate(bids):
        b = f.box(222, 216 + i * 38, f"agent {n}", w=86, h=32, center=True, kind="accent" if n == "b" else "")
        f.edge([tk.right, (b.x, b.cy)], "", head=True)
        f.text(b.x + b.w + 8, b.cy + 4, f"입찰 {sc}", "pf-code")
    f.text(194, 362 - 10, "capabilities 점수가 가장 높은 하나가 맡는다", "pf-note", "middle")
    bb = f.store(566, 220, "공유 보드", "스냅샷", w=120, center=True)
    for i, n in enumerate(["a", "b", "c"]):
        b = f.box(460 + i * 106, 300, f"agent {n}", w=86, h=32, center=True)
        f.edge([(b.cx - 8, b.y), (bb.cx - 20 + i * 20, bb.y + bb.h)], "", head=True)
    f.text(566, 352, "전원이 병렬로 읽고 쓴다, --promote 면 장기 기억으로", "pf-note", "middle")
    return f


def focus_mode() -> Fig:
    f = Fig("focus-mode", 380, "Focus 모드의 한 턴과 화면 배치")
    f.panel(16, 12, 470, 356, "(a) Focus 동안의 한 턴")
    an = f.box(250, 46, "분석", "턴 앞, 다섯 항목", w=130, h=44, center=True)
    ref = f.box(410, 46, "조사", "시작, 검색어가 나올 때", w=130, h=44, center=True)
    user = f.box(84, 150, "사용자 지시", w=100, h=44, center=True, kind="io")
    main = f.box(250, 150, "JARVIS", "오케스트레이터", w=130, h=44, center=True, kind="accent")
    log = f.box(250, 254, "기록", "턴 뒤, 3인칭 서기", w=130, h=44, center=True)
    prog = f.box(410, 254, "진행", "턴 뒤, 단계 완료", w=130, h=44, center=True)
    f.edge([user.right, main.left], "accent")
    start = (user.cx + 6, an.cy - 6)
    f.edge([(user.cx, user.y), (user.cx, an.cy), an.left], "", "같이 시작", at=start, anchor="start", dy=0)
    f.edge([an.right, ref.left], "", "검색어")
    f.edge([an.bottom, main.top], "accent", "Focus 맥락", at=(an.cx + 6, 124), anchor="start", dy=0)
    f.edge([ref.bottom, (ref.cx, main.y + 12), (main.x + main.w, main.y + 12)], "accent", "조사 요약",
           at=(ref.cx - 6, main.y + 6), anchor="end", dy=0)
    f.edge([main.bottom, log.top], "", "응답 뒤", at=(main.cx + 6, 230), anchor="start", dy=0)
    f.edge([(main.x + main.w, main.y + main.h - 12), (prog.cx, main.y + main.h - 12), prog.top], "")
    f.text(250, 334, "sub-agent 넷은 작업 동안 각자의 세션을 유지하고, 결과는 ~/.jarvis/focus/<task_id>/ 에 남는다",
           "pf-note", "middle")
    f.panel(500, 12, 244, 356, "(b) 화면")
    for i in range(3):
        f.chip(510, 46 + i * 92, "", w=10, h=84)
    f.chip(724, 46, "", w=10, h=60)
    f.chip(724, 114, "", w=10, h=200, kind="accent")
    quads = [(524, 46, "조사"), (640, 46, "분석"), (524, 190, "기록"), (640, 190, "진행")]
    for x, y, t in quads:
        f.box(x, y, t, w=80, h=124)
    f.parts.append('<circle class="pf-box pf-box--accent" cx="622" cy="180" r="40"/>')
    f.text(622, 184, "구체 70%", "pf-t", "middle")
    f.text(622, 334, "좌우 카드는 세로 띠로 접힌다", "pf-note", "middle")
    f.text(622, 350, "Conversation 띠만 눌러 펼친다", "pf-note", "middle")
    return f


def extension() -> Fig:
    f = Fig("extension", 356, "~/.jarvis 아래 파일이 기동 때 붙는 자리")
    f.panel(16, 12, 236, 332, "(a) 놓는 파일")
    files = [
        ("tools/", "*.py, *.yaml"),
        ("mcp_servers", "설정 목록"),
        ("skills/", "*.md, 같은 이름 *.py"),
        ("agents/", "*.yaml"),
        ("plugins/", "훅 클래스"),
    ]
    fb = [
        f.box(134, 40 + i * 60, t, sub, w=180, center=True, kind="io", code=False) for i, (t, sub) in enumerate(files)
    ]
    f.panel(266, 12, 478, 332, "(b) 붙는 자리. 파일을 더했으면 재시작한다")
    reg = f.box(390, 50, "도구 레지스트리", "턴마다 다시 읽는다", w=170, center=True)
    sl = f.box(390, 160, "슬래시 커맨드", "/name 이 프롬프트로 펼쳐짐", w=190, center=True)
    ma = f.box(390, 220, "agent_<name>, orchestrate", "서브 에이전트 도구", w=200, center=True)
    f.edge([fb[0].right, reg.left], "accent")
    f.edge([fb[1].right, (300, fb[1].cy), (300, reg.cy + 10), (reg.x, reg.cy + 10)], "accent")
    f.edge([fb[2].right, sl.left], "accent")
    f.edge([fb[3].right, (ma.x, fb[3].cy)], "accent")
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
        hb.append(f.box(640, 30 + i * 52, t, w=170, h=34, center=True, kind="accent" if hook else ""))
    for a, b in zip(hb, hb[1:], strict=False):
        f.edge([a.bottom, b.top], "")
    f.text(640, 336, "강조한 네 칸이 플러그인 훅", "pf-note", "middle")
    f.edge([fb[4].right, (520, fb[4].cy), (520, hb[0].cy), hb[0].left], "accent")
    f.edge([(reg.x + reg.w, reg.cy), (hb[3].x - 6, reg.cy), (hb[3].x - 6, hb[3].cy), hb[3].left], "muted")
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
