"""Draws the performance-experiment charts on the docs feature pages from scripts/experiments/results.json."""

import sys
import json
from pathlib import Path
from scripts.docs_figures import OUT_DIR, WIDTH, Fig, text_width

RESULTS = Path(__file__).resolve().parent / "experiments" / "results.json"
LABEL_FS = 13.5  # 행 이름과 범례 글자 크기(.pf-lab)
BAR_H = 12
BAR_GAP = 3
ROW_GAP = 14
VALUE_W = 52  # 막대 끝 값 글자가 들어갈 오른쪽 여백
SERIES = {"e2b": ("gemma4:e2b", "pf-s1"), "e4b": ("gemma4:e4b", "pf-s2"), "gpt": ("gpt-4o-mini", "pf-s3")}


def legend(fig: Fig, x: float, y: float, keys: list[str], names: dict[str, tuple[str, str]] = SERIES) -> None:
    for key in keys:
        name, cls = names[key]
        fig.parts.append(marker(cls, x + 6, y - 4))
        fig.text(x + 18, y + 1, name, "pf-lab")
        x += 18 + text_width(name, LABEL_FS) + 24


def marker(cls: str, x: float, y: float) -> str:
    """범례 칸. 점 그림의 계열은 그림과 같은 모양(● 같은 약속, ◆ 다른 약속), 나머지는 막대 색 칸이다."""
    if cls == "pf-dot-same":
        return f'<circle class="{cls}" cx="{x}" cy="{y}" r="4"/>'
    if cls == "pf-dot-diff":
        return f'<rect class="{cls}" x="{x - 3.5}" y="{y - 3.5}" width="7" height="7" transform="rotate(45 {x} {y})"/>'
    return f'<rect class="{cls}" x="{x - 6}" y="{y - 6}" width="12" height="12" rx="2"/>'


def axis(
    fig: Fig, x0: float, y0: float, y1: float, w: float, vmax: float, ticks: list[float], fmt: str, title: str = ""
) -> float:
    """세로 눈금선과 눈금 글자, 축 제목을 그리고 그린 바닥 y 를 돌려준다."""
    for t in ticks:
        tx = x0 + w * t / vmax
        fig.parts.append(f'<line class="pf-grid" x1="{tx:.1f}" y1="{y0}" x2="{tx:.1f}" y2="{y1}"/>')
        fig.text(tx, y1 + 15, fmt.format(t), "pf-axis", "middle")
    if title:
        fig.text(x0 + w / 2, y1 + 33, title, "pf-axis-title", "middle")
        return y1 + 33
    return y1 + 15


def grouped_bars(
    fig: Fig,
    x: float,
    y: float,
    w: float,
    rows: list[tuple[str, dict[str, float | None]]],
    keys: list[str],
    vmax: float,
    ticks: list[float],
    fmt: str = "{:.1f}",
    val_fmt: str = "{:.2f}",
    names: dict[str, tuple[str, str]] = SERIES,
    axis_title: str = "",
) -> float:
    """가로 막대 묶음. 행마다 시리즈 막대를 위아래로 쌓고 끝에 값을 적는다. 그린 뒤의 y 를 돌려준다."""
    # 행 이름이 잘리지 않게 이름 칸 폭을 가장 긴 이름에 맞춘다
    label_w = max(110.0, max(text_width(label, LABEL_FS) for label, _ in rows) + 22)
    bar_w = w - label_w - VALUE_W
    top = y
    for label, values in rows:
        group_h = len(keys) * (BAR_H + BAR_GAP) - BAR_GAP
        fig.text(x + label_w - 12, y + group_h / 2 + 4.5, label, "pf-lab", "end")
        for i, key in enumerate(keys):
            v = values.get(key)
            by = y + i * (BAR_H + BAR_GAP)
            if v is None:
                fig.text(x + label_w + 4, by + BAR_H - 1, "측정 안 함", "pf-axis")
                continue
            bw = max(bar_w * min(v, vmax) / vmax, 1.5)
            bx = x + label_w
            fig.parts.append(
                f'<rect class="{names[key][1]}" x="{bx:.1f}" y="{by}" width="{bw:.1f}" height="{BAR_H}" rx="2"/>'
            )
            fig.text(x + label_w + bw + 6, by + BAR_H - 1, val_fmt.format(v), "pf-val")
        y += group_h + ROW_GAP
    return axis(fig, x + label_w, top - 4, y - ROW_GAP + 4, bar_w, vmax, ticks, fmt, axis_title) + 8


def section(fig: Fig, y: float, label: str, draw) -> float:  # type: ignore[no-untyped-def]
    """패널 하나. draw(시작 y) 가 그린 내용의 바닥에 맞춰 패널 높이를 정하고, 패널을 내용 뒤에 깐다."""
    idx = len(fig.parts)
    bottom = draw(y + 40)
    height = bottom - y + 6
    n = len(fig.parts)
    fig.panel(10, y, WIDTH - 20, height, label)
    panel_parts = fig.parts[n:]
    del fig.parts[n:]
    fig.parts[idx:idx] = panel_parts
    return y + height + 10


def bars_with_legend(  # type: ignore[no-untyped-def]
    fig, keys, rows, vmax, ticks, fmt="{:.1f}", val_fmt="{:.2f}", names=SERIES, note="", axis_title=""
):
    def draw(y: float) -> float:
        legend(fig, 30, y + 2, keys, names)
        bottom = grouped_bars(fig, 20, y + 26, WIDTH - 40, rows, keys, vmax, ticks, fmt, val_fmt, names, axis_title)
        if note:
            fig.text(30, bottom + 12, note, "pf-note")
            bottom += 20
        return bottom

    return draw


def load() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


# ── 그림 ──

MODELS = ["e2b", "e4b", "gpt"]
UNIT = [0, 0.5, 1.0]


def finish(fig: Fig, y: float) -> Fig:
    fig.height = y
    return fig


def exp_proactive(r: dict) -> Fig:
    cmp, rep = r["proactive_compare"], r["reply_feedback"]
    names = {"recall": ("recall (말해야 할 때 말함)", "pf-s2"), "fa": ("오경보 (침묵할 때 말함)", "pf-s3")}
    fig = Fig("exp-proactive", 0, "먼저 말하기: 지시문과 decision model 구성별 비교")
    # results.json 의 구성 이름은 가운뎃점으로 이어져 있어 그림에서는 쉼표로 바꿔 적는다
    rows = [
        (f"{c['label'].replace(' · ', ', ')} ({c['threshold']})", {"recall": c["recall"], "fa": c["false_alarm"]})
        for c in cmp["test"]
    ]
    draw = bars_with_legend(fig, list(names), rows, 1.0, UNIT, names=names, axis_title="비율 (0~1)")
    y = section(fig, 10, "(a) 블라인드 시험 상황 20개 × 3회. 괄호는 개발용에서 고른 확신도 임계치", draw)
    rows = [("정확도", {k: rep[k]["accuracy"] for k in MODELS})]
    y = section(
        fig,
        y,
        "(b) 🔔 뒤 짧은 답 12개 × 3회 분류 정확도",
        bars_with_legend(fig, MODELS, rows, 1.0, UNIT, axis_title="정확도 (0~1)"),
    )
    return finish(fig, y)


def exp_inner_thought(r: dict) -> Fig:
    t, fr = r["thought_timing"], r["thought_frames"]
    names = {"local": ("로컬 e4b + e2b", "pf-s2"), "cloud": ("gpt-4o-mini", "pf-s3")}
    fig = Fig("exp-inner-thought", 0, "사고 시점별 응답 속도와 요청 사고 품질")
    rows = []
    for mode in ("before", "race", "after"):
        rows.append((f"{mode}, 첫 글자", {k: t[k][mode]["first"] for k in names}))
        rows.append((f"{mode}, 응답 끝", {k: t[k][mode]["total"] for k in names}))
    draw = bars_with_legend(
        fig, list(names), rows, 25, [0, 5, 10, 15, 20, 25], "{:.0f}", "{:.1f}s", names, axis_title="시간 (초)"
    )
    y = section(fig, 10, "(a) 사고 시점별 응답 시간(초, 중앙값, 4회)", draw)
    rows = [
        ("약속 recall", {k: fr[k]["loop_recall"] for k in MODELS}),
        ("약속 precision", {k: fr[k]["loop_precision"] for k in MODELS}),
    ]
    lat = ", ".join(f"{SERIES[k][0]} {fr[k]['latency_p50']:.1f}초" for k in MODELS)
    note = f"지연 중앙값: {lat}. 유효 프레임은 세 모델 모두 1.00"
    y = section(
        fig,
        y,
        "(b) 입력 12개 × 2회: 약속(open loop)을 잡는가",
        bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note, axis_title="비율 (0~1)"),
    )
    return finish(fig, y)


def exp_open_loop(r: dict) -> Fig:
    plain = r["loop_embedding"].get("none")
    emb = {k: v for k, v in r["loop_embedding"].items() if "pairs" in v}
    fig = Fig("exp-open-loop", 0, "임베딩별 같은 약속과 다른 약속의 코사인 분포")
    lowest = min(p["cos"] for data in emb.values() for p in data["pairs"])
    # 축은 가장 낮은 코사인보다 한 칸(0.1) 아래에서 시작해 끝 점이 이름 글자에 붙지 않게 한다
    lo = int(lowest * 10) / 10 - 0.05
    x0, w, hi = 200, WIDTH - 240, 1.0
    names = {"same": ("같은 약속", "pf-dot-same"), "diff": ("다른 약속", "pf-dot-diff")}

    def draw(y: float) -> float:
        legend(fig, 30, y + 2, ["same", "diff"], names)
        top = y + 22
        y = top + 18
        for name, data in emb.items():
            fig.text(x0 - 12, y + 4, name, "pf-lab", "end")
            acc = f"판정 정확도 {data['same_loop_acc']:.2f}, 잘못 합침 {data['false_merge']}"
            fig.text(x0 - 12, y + 19, acc, "pf-axis", "end")
            for p in data["pairs"]:
                px = x0 + w * (p["cos"] - lo) / (hi - lo)
                if p["same"]:
                    fig.parts.append(f'<circle class="pf-dot-same" cx="{px:.1f}" cy="{y - 2}" r="5"/>')
                else:
                    fig.parts.append(
                        f'<rect class="pf-dot-diff" x="{px - 4.25:.1f}" y="{y + 5}" width="8.5" height="8.5" '
                        f'transform="rotate(45 {px:.1f} {y + 9.25})"/>'
                    )
            y += 48
        bottom = y - 20
        for tick in [t / 10 for t in range(int((lo + 0.05) * 10), 11)]:
            tx = x0 + w * (tick - lo) / (hi - lo)
            fig.parts.append(f'<line class="pf-grid" x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{bottom}"/>')
            fig.text(tx, bottom + 15, f"{tick:.1f}", "pf-axis", "middle")
        fig.text(x0 + w / 2, bottom + 33, "코사인 유사도", "pf-axis-title", "middle")
        rx = x0 + w * (0.85 - lo) / (hi - lo)
        fig.parts.append(f'<line class="pf-ref" x1="{rx:.1f}" y1="{top}" x2="{rx:.1f}" y2="{bottom}"/>')
        fig.text(rx + 5, top + 8, "문턱 0.85", "pf-ref-t")
        if plain:
            acc, merges = plain["same_loop_acc"], plain["false_merge"]
            note = f"임베딩 없이 글자 규칙만 쓰면 판정 정확도 {acc:.2f}, 잘못 합침 {merges}"
            fig.text(30, bottom + 56, note, "pf-note")
            return bottom + 62
        return bottom + 40

    y = section(fig, 10, "약속 18쌍의 코사인: 바꿔 말한 같은 약속(●)과 같은 주제의 다른 약속(◆)", draw)
    return finish(fig, y)


def exp_memory(r: dict) -> Fig:
    lang = r["summary_language"]
    fig = Fig("exp-memory", 0, "/compact 요약의 언어와 사실 보존")

    def ratio(text: str) -> float:
        a, b = (int(n) for n in text.split("/"))
        return a / b

    rows = [
        ("한국어 요약 (이전 지시문)", {k: ratio(lang["before"][k]["korean"]) for k in MODELS}),
        ("한국어 요약 (지금)", {k: ratio(lang["after"][k]["korean"]) for k in MODELS}),
        ("낱말 그대로 (이전 지시문)", {k: lang["before"][k]["verbatim"] for k in MODELS}),
        ("낱말 그대로 (지금)", {k: lang["after"][k]["verbatim"] for k in MODELS}),
    ]
    note = "사실 보존율(판정 모델 gpt-4o-mini 고정)은 지시문을 바꾸기 전과 후 모두 세 모델 1.00"
    draw = bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note, axis_title="비율 (0~1)")
    y = section(fig, 10, "한국어 대화 3개 × 3회 요약, 심어 둔 사실 12개", draw)
    return finish(fig, y)


# 전후 비교 그림의 점 반지름(지름 8px 이상)과 마우스 판정 반지름
DOT_R = 4.5
HIT_R = 11
DUMBBELL_ROW_H = 38  # 원점 값을 점 아래에 적어도 다음 행 이름과 닿지 않는 높이


def _dot(fig: Fig, x: float, y: float, side: str, tip: str) -> None:
    """빈 점(이전)과 찬 점(지금). 판정 원을 점보다 크게 깔고 title 로 값을 띄운다."""
    fig.parts.append(
        f'<g><title>{tip}</title><circle class="pf-hit" cx="{x:.1f}" cy="{y:.1f}" r="{HIT_R}"/>'
        f'<circle class="pf-dot--{side}" cx="{x:.1f}" cy="{y:.1f}" r="{DOT_R}"/></g>'
    )


def _legend_pair(fig: Fig, x: float, y: float) -> None:
    for side, name in (("before", "이전 코드"), ("after", "지금")):
        fig.parts.append(f'<line class="pf-line--{side}" x1="{x}" y1="{y}" x2="{x + 26}" y2="{y}"/>')
        fig.parts.append(f'<circle class="pf-dot--{side}" cx="{x + 13}" cy="{y}" r="{DOT_R}"/>')
        fig.text(x + 34, y + 4.5, name, "pf-lab")
        x += 34 + text_width(name, LABEL_FS) + 24


def _line_panel(  # type: ignore[no-untyped-def]
    fig: Fig, x: float, y: float, w: float, h: float, label: str, sub: str, curves: dict, mark: tuple | None = None
) -> None:
    """x 는 쌓인 항목 수(순서 척도), y 는 0~100%. 선 끝에 값을 직접 적는다."""
    fig.panel(x, y, w, h, label)
    fig.text(x + 12, y + 41, sub, "pf-lab")
    left, right, top, bottom = x + 48, x + w - 98, y + 64, y + h - 30
    xs = list(curves["after"])
    step = (right - left) / (len(xs) - 1)

    def px(i: int) -> float:
        return left + i * step

    def py(v: float) -> float:
        return bottom - (bottom - top) * v

    for t in (0, 0.5, 1.0):
        fig.parts.append(f'<line class="pf-grid" x1="{left}" y1="{py(t):.1f}" x2="{right}" y2="{py(t):.1f}"/>')
        fig.text(left - 8, py(t) + 3.5, f"{t:.0%}", "pf-axis", "end")
    for i, n in enumerate(xs):
        fig.text(px(i), bottom + 15, n, "pf-axis", "middle")
    if mark is not None:
        at, text = mark
        mx = px(xs.index(at))
        fig.parts.append(f'<line class="pf-mark" x1="{mx:.1f}" y1="{top - 6}" x2="{mx:.1f}" y2="{bottom}"/>')
        # 오른쪽 위아래로 두 선이 지나가지 않는 띠(50% 근처)에 적는다
        fig.text(mx + 6, top + (bottom - top) / 2 - 6, text, "pf-mark-t")
    for side, name in (("before", "이전 코드"), ("after", "지금")):
        values = [curves[side][n] for n in xs]
        d = "M" + " L".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(values))
        fig.parts.append(f'<path class="pf-line--{side}" d="{d}"/>')
        for i, v in enumerate(values):
            _dot(fig, px(i), py(v), side, f"{name}, {xs[i]}개 뒤: {v:.0%}")
        fig.text(right + 12, py(values[-1]) + 4, f"{name} {values[-1]:.0%}", "pf-val")


def _dumbbell(  # type: ignore[no-untyped-def]
    fig: Fig,
    x: float,
    y: float,
    w: float,
    rows: list,
    vmax: float,
    ticks: list,
    fmt,
    label_w: float = 196,
    tick_fmt=None,
) -> float:
    """행마다 이전(빈 점)에서 지금(찬 점)으로 잇는다. 같은 값이면 점 하나와 '전후 같음' 을 적는다."""
    left, right = x + label_w, x + w - 56
    row_h = DUMBBELL_ROW_H
    tick_fmt = tick_fmt or fmt

    def px(v: float) -> float:
        return left + (right - left) * min(v, vmax) / vmax

    bottom = y + row_h * len(rows)
    for t in ticks:
        fig.parts.append(f'<line class="pf-grid" x1="{px(t):.1f}" y1="{y - 6}" x2="{px(t):.1f}" y2="{bottom - 8}"/>')
        fig.text(px(t), bottom + 6, tick_fmt(t), "pf-axis", "middle")
    for i, (name, before, after) in enumerate(rows):
        cy = y + i * row_h + 8
        fig.text(left - 14, cy + 4, name, "pf-lab", "end")
        if before == after:
            _dot(fig, px(after), cy, "after", f"{name}: 전후 모두 {fmt(after)}")
            fig.text(px(after) + 12, cy + 4, f"{fmt(after)}, 전후 같음", "pf-val")
            continue
        fig.parts.append(f'<line class="pf-link" x1="{px(before):.1f}" y1="{cy}" x2="{px(after):.1f}" y2="{cy}"/>')
        _dot(fig, px(before), cy, "before", f"{name}, 이전 코드: {fmt(before)}")
        _dot(fig, px(after), cy, "after", f"{name}, 지금: {fmt(after)}")
        (lo_x, lo_v), (hi_x, hi_v) = sorted([(px(before), before), (px(after), after)])
        fig.text(hi_x + 10, cy + 4, fmt(hi_v), "pf-val")
        if lo_x - left > 30:
            fig.text(lo_x - 10, cy + 4, fmt(lo_v), "pf-val", "end")
        else:  # 축 원점에 붙은 값은 이름과 겹치지 않게 점 아래에 적는다
            fig.text(lo_x, cy + 17, fmt(lo_v), "pf-axis", "middle")
    return bottom + 14


def exp_memory_recall(r: dict) -> Fig:
    m = r["memory_recall"]
    before, after = m["before"], m["after"]
    fig = Fig("exp-memory-recall", 0, "회상 품질: 이전 코드와 지금")
    pct = "{:.0%}".format
    _legend_pair(fig, 22, 22)
    fig.text(WIDTH - 22, 26, "점에 마우스를 올리면 값이 보인다", "pf-axis", "end")

    y, half = 40, (WIDTH - 30) / 2
    curve = {side: m[side]["salient_hit_at_3"] for side in ("before", "after")}
    _line_panel(
        fig,
        10,
        y,
        half,
        236,
        "(a) 200일 전 큰 사건을 떠올리는 비율",
        "가로: 그 뒤 쌓인 같은 낱말의 사소한 일화 수",
        curve,
    )
    curve = {side: m[side]["core_fact_kept"] for side in ("before", "after")}
    _line_panel(
        fig,
        20 + half,
        y,
        half,
        236,
        "(b) 100일 전 핵심 사실이 고정 블록에 남는 비율",
        "가로: 그 뒤 쌓인 사소한 의미 사실 수",
        curve,
        mark=("12", "이전 후보 풀 12개"),
    )
    y += 246

    rows = [
        ("조사 붙은 질의 (10개)", before["particle_hit_at_3"], after["particle_hit_at_3"]),
        ('"그거 다시 해줘" 뒤 회상 (8개)', before["deictic_recall"], after["deictic_recall"]),
        ('"그거 기억해" 로 남긴 기억 (8개)', before["referent_recall"], after["referent_recall"]),
        ("엉뚱한 질의에 끼어듦 (8개, 낮을수록 좋음)", before["overreach_rate"], after["overreach_rate"]),
    ]
    height = 52 + DUMBBELL_ROW_H * len(rows) + 22
    fig.panel(10, y, WIDTH - 20, height, "(c) 시나리오별 적중률")
    _dumbbell(fig, 20, y + 52, WIDTH - 40, rows, 1.0, [0, 0.5, 1.0], pct, label_w=262)
    y += height + 10

    left_w = 236
    lower_h = 46 + DUMBBELL_ROW_H * 3 + 52
    fig.panel(10, y, left_w, lower_h, "(d) 무관한 10턴의 되뇌기 횟수")
    k = "rehearsal_per_fixed_fact"
    for i, (side, v, name) in enumerate((("before", before[k], "이전 코드"), ("after", after[k], "지금"))):
        cx = 34 + i * 108
        fig.parts.append(f'<circle class="pf-dot--{side}" cx="{cx}" cy="{y + 70}" r="{DOT_R}"/>')
        fig.text(cx + 12, y + 81, f"{v:.0f}", "pf-hero")
        fig.text(cx + 12, y + 100, name, "pf-lab")
    fig.text(22, y + lower_h - 14, "고정 사실 하나당. 질의에 걸린 것만 센다", "pf-note")

    pb, pa = before["postgres"], after["postgres"]
    rows = [
        ("recall p50", pb["recall_p50_ms"], pa["recall_p50_ms"]),
        ("recall p95", pb["recall_p95_ms"], pa["recall_p95_ms"]),
        ("fixed_facts p50", pb["fixed_p50_ms"], pa["fixed_p50_ms"]),
    ]
    rx, rw = 20 + left_w, WIDTH - 30 - left_w
    fig.panel(rx, y, rw, lower_h, "(e) Postgres 지연 (ms, 낮을수록 좋음)")
    _dumbbell(
        fig,
        rx + 10,
        y + 46,
        rw - 20,
        rows,
        10.0,
        [0, 5, 10],
        lambda v: f"{v:.1f}",
        label_w=128,
        tick_fmt=lambda v: f"{v:.0f} ms",
    )
    note = "일화 2,000개, pgvector, 질의 200회. LLM 호출 한 번(수백 ms 이상)에 비하면 작다"
    fig.text(rx + 12, y + lower_h - 14, note, "pf-note")
    return finish(fig, y + lower_h + 10)


def check_matrix(fig: Fig, x: float, y: float, cols: list[str], rows: list[tuple[str, list[str]]]) -> float:
    """단계 × 지표 준수표. 전부 지키면 채운 원, 일부면 지킨 비율만큼 채운 원, 하나도 못 지키면 빨간 빈 원이다."""
    col_w = (WIDTH - x - 40 - 230) / len(cols)
    for i, c in enumerate(cols):
        fig.text(x + 230 + col_w * (i + 0.5), y, c, "pf-lab", "middle")
    y += 24
    for label, cells in rows:
        fig.text(x + 220, y + 4, label, "pf-lab", "end")
        for i, cell in enumerate(cells):
            cx = x + 230 + col_w * (i + 0.5)
            if "/" in cell:
                a, b = (int(n) for n in cell.split("/"))
                if 0 < a < b:
                    _part_circle(fig, cx - 18, y, a, b)
                else:
                    cls = "pf-ok" if a == b else "pf-zero"
                    fig.parts.append(f'<circle class="{cls}" cx="{cx - 18:.1f}" cy="{y}" r="6"/>')
                fig.text(cx - 6, y + 4, cell, "pf-val")
            else:
                fig.text(cx, y + 4, cell, "pf-axis", "middle")
        y += 26
    return matrix_legend(fig, x + 230, y + 4)


def _part_circle(fig: Fig, cx: float, cy: float, a: int, b: int) -> None:
    """지킨 비율만큼 아래에서 위로 채운 원."""
    fig.parts.append(f'<circle class="pf-part" cx="{cx:.1f}" cy="{cy}" r="6"/>')
    fill_h = 12 * a / b
    clip = f"{fig.name}-c{len(fig.parts)}"
    box = f'<rect x="{cx - 6:.1f}" y="{cy + 6 - fill_h:.1f}" width="12" height="{fill_h:.1f}"/>'
    fig.parts.append(f'<clipPath id="{clip}">{box}</clipPath>')
    fig.parts.append(f'<circle class="pf-ok" cx="{cx:.1f}" cy="{cy}" r="6" clip-path="url(#{clip})"/>')


def matrix_legend(fig: Fig, x: float, y: float) -> float:
    """준수표 아래의 기호 설명. 그린 바닥 y 를 돌려준다."""
    items = [("pf-ok", "모두 지킴"), ("part", "일부, 지킨 비율만큼 채움"), ("pf-zero", "하나도 못 지킴")]
    for cls, name in items:
        if cls == "part":
            _part_circle(fig, x + 6, y, 1, 2)
        else:
            fig.parts.append(f'<circle class="{cls}" cx="{x + 6:.1f}" cy="{y}" r="6"/>')
        fig.text(x + 18, y + 4.5, name, "pf-axis")
        x += 18 + text_width(name, 12.5) + 22
    return y + 12


def exp_approval(r: dict) -> Fig:
    a, c = r["approval_compliance"], r["reply_approval"]
    fig = Fig("exp-approval", 0, "거부 뒤 승인 흐름 준수와 음성 승인 분류")
    cols = ["도구 호출", "정해진 거부 문구", "재요청 시 다시 물음"]
    y = section(
        fig,
        10,
        '(a) 승인이 필요한 요청 → 거부 → "다시 해 줘"',
        lambda y0: check_matrix(fig, 20, y0 + 4, cols, [(row["stage"], row["cells"]) for row in a]),
    )
    rows = [
        ("결정 정확도", {k: c[k]["decision_accuracy"] for k in MODELS}),
        ("놓친 허용 비율", {k: c[k]["missed_allow"] / 18 for k in MODELS}),
        ("위험한 허용", {k: c[k]["unsafe_allow"] for k in MODELS}),
    ]
    note = "결정 정확도는 실행(allow, always)과 거부(deny, unclear)만 맞았는지 본다. 놓친 허용은 허용 18번 중 비율"
    draw = bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note, axis_title="비율 (0~1)")
    y = section(fig, y, "(b) 승인 답 12개 × 3회, 분류기 단독(키워드 단계 없이)", draw)
    return finish(fig, y)


def exp_voice(r: dict) -> Fig:
    p = r["piper"]
    names = {"audio": ("음성 길이", "pf-s1"), "synth": ("합성 시간", "pf-s3")}
    fig = Fig("exp-voice", 0, "Piper 영어 음성 합성 시간과 음성 길이")
    rows = [(f"{s['chars']}자 문장", {"audio": s["audio_s"], "synth": s["synth_s"]}) for s in p]
    draw = bars_with_legend(
        fig, list(names), rows, 7, list(range(8)), "{:.0f}", "{:.2f}s", names, axis_title="시간 (초)"
    )
    y = section(fig, 10, "Piper(high) 합성, 컨테이너 CPU 14코어: 합성 시간은 음성 길이의 약 1/5", draw)
    return finish(fig, y)


def exp_team(r: dict) -> Fig:
    d = r["delegation"]
    names = {"local": ("gemma4:e4b (두 에이전트)", "pf-s2"), "cloud": ("gpt-4o-mini (두 에이전트)", "pf-s3")}
    fig = Fig("exp-team", 0, "JARVIS 가 KAREN 에게 맡기는 위임 실험")
    rows = [("위임 한 번", {k: d[k]["total_s"] for k in names})]
    note = "ask_agent 사용 3/3, KAREN 의 sh_notice 호출 3/3 (두 모델 모두)"
    draw = bars_with_legend(
        fig, list(names), rows, 40, [0, 10, 20, 30, 40], "{:.0f}", "{:.1f}s", names, note, axis_title="시간 (초)"
    )
    y = section(fig, 10, "청약 공고 찾기 위임 3회: 끝까지 걸린 시간(초, 중앙값)", draw)
    return finish(fig, y)


def exp_focus(r: dict) -> Fig:
    f = r["focus"]
    names = {"local": ("gemma4:e4b", "pf-s2"), "cloud": ("gpt-4o-mini", "pf-s3")}
    fig = Fig("exp-focus", 0, "Focus 시작 시간과 조사 형식 준수")
    rows = [(t["task"], {"local": t["local"], "cloud": t["cloud"]}) for t in f["first_reply"]]
    draw = bars_with_legend(
        fig, list(names), rows, 25, [0, 5, 10, 15, 20, 25], "{:.0f}", "{:.1f}s", names, axis_title="첫 응답까지 (초)"
    )
    y = section(fig, 10, "(a) /focus 부터 첫 응답 글자까지(초), 작업 2개", draw)
    cols = ["gemma4:e4b", "gpt-4o-mini"]
    y = section(
        fig,
        y,
        "(b) 조사 결과가 지시문 형식을 지켰는가",
        lambda y0: check_matrix(fig, 20, y0 + 4, cols, [(row["rule"], row["cells"]) for row in f["reference"]]),
    )
    return finish(fig, y)


PCT = "{:.0%}"
VERSIONS_196 = {
    "d07aa36_before_196": ("#196 전", "pf-s1"),
    "b3b2b0b_after_196": ("#196 뒤", "pf-s3"),
    "3c7e938_after_197": ("#197 뒤 (현재)", "pf-s2"),
}
SCENARIOS = {
    "steady_5": "(a) 주기마다 5건, 상한 안",
    "burst_50": "(b) 첫 주기에 50건 몰림",
    "overload_30": "(c) 주기마다 30건, 상한 20건을 계속 넘음",
}


def exp_mcp(r: dict) -> Fig:
    d = r["external_delivery"]
    fig = Fig("exp-mcp", 0, "외부 이벤트를 끝내 전하지 못한 비율")
    y = 10.0
    for scenario, title in SCENARIOS.items():
        rows = [
            (
                f"사고 실패율 {row['fail_rate']:.0%}",
                {label: d[label][scenario][i]["loss_rate"] for label in VERSIONS_196},
            )
            for i, row in enumerate(d["3c7e938_after_197"][scenario])
        ]
        draw = bars_with_legend(
            fig,
            list(VERSIONS_196),
            rows,
            1.0,
            [0, 0.25, 0.5, 0.75, 1.0],
            PCT,
            "{:.1%}",
            VERSIONS_196,
            axis_title="잃은 이벤트 비율",
        )
        y = section(fig, y, title, draw)
    return finish(fig, y)


def exp_scheduling(r: dict) -> Fig:
    d = r["housing_delivery"]
    names = {"b3b2b0b_before_197": ("#197 전", "pf-s1"), "3c7e938_after_197": ("#197 뒤 (현재)", "pf-s2")}
    fig = Fig("exp-scheduling", 0, "알림 실패율에 따라 끝내 알리지 못한 공고 비율")
    rows = [
        (f"알림 실패율 {row['fail_rate']:.0%}", {label: d[label]["rows"][i]["miss_rate"] for label in names})
        for i, row in enumerate(d["3c7e938_after_197"]["rows"])
    ]
    after = d["3c7e938_after_197"]
    note = f"공고 {after['rows'][0]['posted']}건, 시드 {after['seeds']}개, 두 번 알림 0건"
    draw = bars_with_legend(
        fig, list(names), rows, 0.4, [0, 0.1, 0.2, 0.3, 0.4], PCT, "{:.1%}", names, note, axis_title="놓친 공고 비율"
    )
    y = section(fig, 10, "housing_watch 를 매일 한 번 돌린 60일 시뮬레이션", draw)
    return finish(fig, y)


def exp_extension(r: dict) -> Fig:
    d = r["tool_reload"]["after_cache_fix"]
    restart = r["tool_reload"]["3c7e938_after_195"]["restart"]["restart"]
    names = {"p50": ("p50", "pf-s2"), "p95": ("p95", "pf-s3")}
    fig = Fig("exp-extension", 0, "도구 파일을 고친 뒤 쓸 수 있을 때까지 걸린 시간")
    rows = [
        ("새 파일 (감시)", {k: d["watch"]["new_file"][f"{k}_ms"] for k in names}),
        ("고친 파일 (감시)", {k: d["watch"]["modified_file"][f"{k}_ms"] for k in names}),
        ("재시작 (프로세스와 앱 조립만)", {k: restart[f"{k}_ms"] for k in names}),
    ]
    note = "#195 전에는 감시가 없어 새 도구가 5초 뒤에도 보이지 않았다(재시작 필요)"
    draw = bars_with_legend(
        fig, list(names), rows, 400, [0, 100, 200, 300, 400], "{:.0f}", "{:.0f}ms", names, note, axis_title="시간 (ms)"
    )
    y = section(fig, 10, "반영까지 걸린 시간, 감시 30회, 재시작 10회", draw)
    return finish(fig, y)


def exp_sessions(r: dict) -> Fig:
    d = r["session_race"]
    names = {
        "both_gone": ("둘 다 지워짐", "pf-s1"),
        "both_alive": ("둘 다 남음", "pf-s2"),
        "alive_without_history": ("기록 없이 세션만 남음", "pf-s3"),
    }
    fig = Fig("exp-sessions", 0, "같은 세션을 지우면서 다시 열 때의 끝 상태")
    rows = [
        ("#195 전", {k: d["eb41779_before_195"][k] for k in names}),
        ("#195 뒤 (현재)", {k: d["d07aa36_after_195"][k] for k in names}),
    ]
    draw = bars_with_legend(
        fig, list(names), rows, 1400, [0, 350, 700, 1050, 1400], "{:.0f}", "{:.0f}회", names, axis_title="횟수"
    )
    y = section(fig, 10, f"삭제와 다시 열기를 겹쳐 {d['d07aa36_after_195']['trials']}회 실행", draw)
    return finish(fig, y)


def exp_orchestration(r: dict) -> Fig:
    d = r["orchestration_patterns"]
    names = {"wall": ("끝까지 걸린 시간", "pf-s2")}
    fig = Fig("exp-orchestration", 0, "같은 작업을 패턴별로 맡겼을 때의 시간")
    rows = [
        (f"{row['pattern'].replace(',', ' + ')} (호출 {row['sub_agent_calls']})", {"wall": row["wall_s_mean"]})
        for row in d["rows"]
    ]
    note = (
        f"서브 에이전트 한 번 {d['sub_agent_s']}초, 감독 모델 한 번 {d['supervisor_model_s']}초로 고정,"
        f" {d['repeats']}회 평균"
    )
    draw = bars_with_legend(
        fig, list(names), rows, 2.0, [0, 0.5, 1.0, 1.5, 2.0], "{:.1f}", "{:.2f}s", names, note, axis_title="시간 (초)"
    )
    y = section(fig, 10, "패턴별 걸린 시간과 서브 에이전트 호출 수", draw)
    return finish(fig, y)


def exp_architecture(r: dict) -> Fig:
    d = r["turn_overhead"]
    names = {
        "framework_ms": ("모델 밖 전체", "pf-s2"),
        "repo_read_ms": ("기록 읽기", "pf-s3"),
        "memory": ("기억 (observe + reinforce)", "pf-s1"),
    }
    configs = {
        "jsonl_memory_on": "JSONL, 기억 켬",
        "jsonl_memory_off": "JSONL, 기억 끔",
        "dict_memory_on": "메모리 저장, 기억 켬",
    }
    windows = {"turns_1_20": "1~20턴", "turns_181_200": "181~200턴"}
    fig = Fig("exp-architecture", 0, "요청 한 번에 모델 밖에서 쓰는 시간")
    rows = []
    for key, label in configs.items():
        for window, wlabel in windows.items():
            s = d[key][window]
            rows.append(
                (
                    f"{label}, {wlabel}",
                    {
                        "framework_ms": s["framework_ms"],
                        "repo_read_ms": s["repo_read_ms"],
                        "memory": s["memory_observe_ms"] + s["memory_reinforce_ms"],
                    },
                )
            )
    draw = bars_with_legend(
        fig, list(names), rows, 18, [0, 6, 12, 18], "{:.0f}", "{:.2f}ms", names, axis_title="턴당 시간 (ms, 중앙값)"
    )
    y = section(fig, 10, "모델 시간을 뺀 턴당 처리 시간, 세션 3개 x 200턴", draw)
    return finish(fig, y)


# 실패 반성의 수정 종류. 거부는 거름망이나 스키마가 두 번 막은 것, 기록 안 함은 execution_slip 이다
REFLECT_KINDS = {
    "procedure": ("절차 개정", "pf-s2"),
    "task_pattern": ("작업 패턴", "pf-s1"),
    "no_change": ("기록 안 함", "pf-bar"),
    "refused": ("거부", "pf-s3"),
}
BACKBONE_NAMES = {"gpt-4o-mini": "gpt-4o-mini", "gemma4:e4b": "gemma4:e4b", "gemma4:e2b-it-qat": "gemma4:e2b"}


def _stacked(fig: Fig, x: float, y: float, w: float, rows: list[tuple[str, dict[str, int]]]) -> float:
    """행마다 수정 종류를 비율로 이어 붙인 가로 막대. 칸 안에 건수를 적는다(좁으면 생략)."""
    label_w = max(text_width(label, LABEL_FS) for label, _ in rows) + 22
    bar_w = w - label_w - 40
    for label, counts in rows:
        total = sum(counts.get(k, 0) for k in REFLECT_KINDS) or 1
        fig.text(x + label_w - 12, y + BAR_H + 2, label, "pf-lab", "end")
        bx = x + label_w
        for key, (name, cls) in REFLECT_KINDS.items():
            n = counts.get(key, 0)
            if not n:
                continue
            seg = bar_w * n / total
            fig.parts.append(
                f'<g><title>{label}, {name}: {n}</title><rect class="{cls}" x="{bx:.1f}" y="{y}"'
                f' width="{seg:.1f}" height="{BAR_H + 6}" rx="2"/></g>'
            )
            if seg > 18:
                # 진한 칸(절차 개정, 거부)은 밝은 글자로 적어야 읽힌다
                text_cls = "pf-badge-t" if cls in ("pf-s2", "pf-s3") else "pf-val"
                fig.text(bx + seg / 2, y + BAR_H + 1, str(n), text_cls, "middle")
            bx += seg
        fig.text(x + label_w + bar_w + 8, y + BAR_H + 1, f"{total}", "pf-axis")
        y += BAR_H + 6 + ROW_GAP
    return y


def _count_lines(fig: Fig, x: float, y: float, w: float, h: float, xs: list[str], curves: dict) -> float:
    """x 는 성공 횟수, y 는 파일 수. 세대 방식은 이전(점선, 빈 점), 수렴 방식은 지금(실선, 찬 점) 모양이다."""
    left, right, top, bottom = x + 48, x + w - 130, y + 10, y + h
    vmax = max(max(values[n] for n in xs) for _, values in curves.values()) or 1
    step = (right - left) / (len(xs) - 1)

    def px(i: int) -> float:
        return left + i * step

    def py(v: float) -> float:
        return bottom - (bottom - top) * v / vmax

    for t in sorted({0, vmax // 2, vmax}):
        fig.parts.append(f'<line class="pf-grid" x1="{left}" y1="{py(t):.1f}" x2="{right}" y2="{py(t):.1f}"/>')
        fig.text(left - 8, py(t) + 3.5, f"{t}", "pf-axis", "end")
    for i, n in enumerate(xs):
        fig.text(px(i), bottom + 15, n, "pf-axis", "middle")
    fig.text((left + right) / 2, bottom + 33, "같은 작업 종류의 성공 횟수", "pf-axis-title", "middle")
    for side, (name, values) in curves.items():
        vals = [values[n] for n in xs]
        d = "M" + " L".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(vals))
        fig.parts.append(f'<path class="pf-line--{side}" d="{d}"/>')
        for i, v in enumerate(vals):
            _dot(fig, px(i), py(v), side, f"{name}, 성공 {xs[i]}번: 파일 {v}개")
        fig.text(right + 12, py(vals[-1]) + 4, f"{name} {vals[-1]}개", "pf-val")
    return bottom + 40


def exp_procedures(r: dict) -> Fig:
    d = r["procedure_reflection"]
    fig = Fig("exp-procedures", 0, "절차 학습: 실패 반성의 held-out 정확도, 백본별 수정 종류, 절차 파일 수")
    y = 10.0
    e2 = d.get("emma2", {})
    backbones = e2.get("backbones", {})
    held = backbones.get("gpt-4o-mini", {}).get("heldout")
    if held:
        names = {"gpt": ("gpt-4o-mini", "pf-s3")}
        arms = [("반성 없음", "none"), ("거름망 없는 반성", "unguarded"), ("거름망 있는 반성", "guarded")]
        rows = [(f"{label} ({held[k]['correct']}/{held[k]['n']})", {"gpt": held[k]["accuracy"]}) for label, k in arms]
        draw = bars_with_legend(
            fig, list(names), rows, 0.4, [0, 0.1, 0.2, 0.3, 0.4], "{:.1f}", "{:.3f}", names, axis_title="정확도"
        )
        y = section(fig, y, f"(a) BBEH-mini held-out {e2['heldout']}문항, train {e2['train']}문항으로 학습", draw)
    rows_k = [
        (f"{BACKBONE_NAMES.get(name, name)}, {'거름망 있음' if arm == 'guarded' else '거름망 없음'}", row[arm]["kinds"])
        for name, row in backbones.items()
        for arm in ("unguarded", "guarded")
        if arm in row
    ]
    if rows_k:

        def draw_k(top: float) -> float:
            legend(fig, 30, top + 2, list(REFLECT_KINDS), REFLECT_KINDS)
            return _stacked(fig, 20, top + 26, WIDTH - 40, rows_k)

        y = section(fig, y, "(b) 실패 묶음마다 받아들인 수정 종류. 막대 끝은 묶음 수", draw_k)
    e1 = d.get("emma1")
    if e1:
        xs = [str(n) for n in e1["successes"]]
        curves = {"before": ("세대 방식", e1["generational_files"]), "after": ("수렴 방식", e1["converged_files"])}

        def draw_l(top: float) -> float:
            _legend_named(fig, 30, top + 2, ("세대 방식(이전)", "수렴 방식(지금)"))
            return _count_lines(fig, 20, top + 22, WIDTH - 40, 150, xs, curves)

        y = section(fig, y, "(c) 작업 종류 하나의 성공이 쌓일 때 절차 파일 수(LLM 없이 합성 일화)", draw_l)
    return finish(fig, y)


def _legend_named(fig: Fig, x: float, y: float, names: tuple[str, str]) -> None:
    for side, name in zip(("before", "after"), names, strict=True):
        fig.parts.append(f'<line class="pf-line--{side}" x1="{x}" y1="{y}" x2="{x + 26}" y2="{y}"/>')
        fig.parts.append(f'<circle class="pf-dot--{side}" cx="{x + 13}" cy="{y}" r="{DOT_R}"/>')
        fig.text(x + 34, y + 4.5, name, "pf-lab")
        x += 34 + text_width(name, LABEL_FS) + 24


NET_ARMS = {
    "rag": ("rag (기준선)", "pf-ok"),
    "raw": ("raw", "pf-s1"),
    "turns": ("turns", "pf-s2"),
    "turns+src": ("turns+src", "pf-s3"),
}
NET_BENCH = {"longmemeval_s": "LongMemEval-s", "personamem_v2": "PersonaMem-v2", "minteval": "MINT-Eval"}


def _diverging(fig: Fig, x: float, y: float, w: float, rows: list, vmax: float) -> float:
    """가운데 0 에서 tax 는 왼쪽(주황), benefit 은 오른쪽(청록)으로 뻗고 오른쪽 끝에 net 을 적는다."""
    label_w, net_w = 218, 78
    mid = x + label_w + (w - label_w - net_w) / 2
    half = (w - label_w - net_w) / 2 - 8
    top = y
    for name, benefit, tax, net in rows:
        fig.text(x + label_w - 12, y + BAR_H - 1, name, "pf-lab", "end")
        tw, bw = half * tax / vmax, half * benefit / vmax
        for cls, bx, width in (("pf-s3", mid - tw, tw), ("pf-s2", mid, bw)):
            fig.parts.append(
                f'<rect class="{cls}" x="{bx:.1f}" y="{y}" width="{max(width, 1.5):.1f}" height="{BAR_H}" rx="2"/>'
            )
        fig.text(x + w - 8, y + BAR_H - 1, f"net {net:+.0%}", "pf-val", "end")
        y += BAR_H + ROW_GAP
    bottom = y - ROW_GAP + 4
    for t in (-vmax, -vmax / 2, 0, vmax / 2, vmax):
        tx = mid + half * t / vmax
        fig.parts.append(f'<line class="pf-grid" x1="{tx:.1f}" y1="{top - 4}" x2="{tx:.1f}" y2="{bottom}"/>')
        fig.text(tx, bottom + 15, f"{abs(t):.0%}", "pf-axis", "middle")
    fig.text(mid - half / 2, bottom + 33, "tax (RAG 는 맞고 비교군은 틀림)", "pf-axis-title", "middle")
    fig.text(mid + half / 2, bottom + 33, "benefit (RAG 는 틀리고 비교군은 맞음)", "pf-axis-title", "middle")
    return bottom + 41


def exp_memory_net_value(r: dict) -> Fig:
    m = r["memory_net_value"]
    benches = [b for b in NET_BENCH if b in m["benchmarks"]]
    title = "Memory Tax 벤치마크 셋: 비교군별 정답률, RAG 대비 benefit 과 tax, 턴 일화 증거 보존"
    fig = Fig("exp-memory-net-value", 0, title)
    rows = [
        (NET_BENCH[b], {a: m["benchmarks"][b]["arms"][a]["summary"]["accuracy"] for a in NET_ARMS}) for b in benches
    ]
    draw = bars_with_legend(fig, list(NET_ARMS), rows, 1.0, UNIT, names=NET_ARMS, axis_title="정답률 (0~1)")
    y = section(fig, 10, f"(a) 비교군별 정답률. 노출 예산 {m['config']['budget_chars']:,}자, 판정 gpt-4o-mini", draw)

    rows = []
    for b in benches:
        for a in ("raw", "turns", "turns+src"):
            v = m["benchmarks"][b]["net"][a]
            rows.append((f"{NET_BENCH[b]}, {a}", v["benefit_rate"], v["tax_rate"], v["net_rate"]))
    vmax = max(0.25, max(max(b, t) for _, b, t, _ in rows))
    vmax = round(vmax + 0.049, 1)
    y = section(
        fig, y, "(b) RAG 대비 질문 단위 benefit 과 tax(질문 수 대비 비율)",
        lambda yy: _diverging(fig, 20, yy, WIDTH - 40, rows, vmax),
    )

    loss = m["turn_loss"]
    rows = [
        ("답(assistant) 정답 턴", loss["before"]["assistant"]["preserved"], loss["after"]["assistant"]["preserved"]),
        ("발화(user) 정답 턴", loss["before"]["user"]["preserved"], loss["after"]["user"]["preserved"]),
        ("전체 정답 턴", loss["before"]["all"]["preserved"], loss["after"]["all"]["preserved"]),
    ]
    mt3 = m["benchmarks"].get("longmemeval_s", {}).get("mt3")
    if mt3:
        rows.append(("turns 정답률 (표본 60)", mt3["turns_before"]["summary"]["accuracy"],
                     mt3["turns_after"]["summary"]["accuracy"]))
    height = 52 + DUMBBELL_ROW_H * len(rows) + 40
    fig.panel(10, y, WIDTH - 20, height, "(c) 턴 일화에 정답이 남는 비율: 1,000자 자르기(이전 코드)와 조각 일화(지금)")
    _legend_pair(fig, 30, y + 40)
    # 100% 에 붙은 "전후 같음" 이 패널 밖으로 나가지 않게 오른쪽을 비운다
    bottom = _dumbbell(fig, 20, y + 64, WIDTH - 130, rows, 1.0, [0, 0.5, 1.0], "{:.0%}".format, label_w=196)
    a = loss["before"]["assistant"]
    held = loss["before"]["all"]["holding"]
    note = f"LongMemEval-s 500문항, 정답 낱말이 원문에 있는 정답 턴 {held}개(답 {a['holding']}개)"
    fig.text(22, bottom + 8, note, "pf-note")
    y += height + 24

    svc = m["benchmarks"].get("longmemeval_s", {}).get("service")
    if svc:
        before, after = svc["arms"]["turns"]["summary"], svc["arms"]["turns+src"]["summary"]
        rows = [(name, before[k], after[k]) for name, k in
                (("정답률", "accuracy"), ("증거 세션 재현율", "session_recall"), ("증거 턴 재현율", "turn_recall"))]
        height = 52 + DUMBBELL_ROW_H * len(rows) + 40
        fig.panel(10, y, WIDTH - 20, height, "(d) 실서비스 블록(핵심 사실 3 + 회상 3): 출처 회상 없음과 있음")
        _legend_pair(fig, 30, y + 40)
        bottom = _dumbbell(fig, 20, y + 64, WIDTH - 130, rows, 1.0, [0, 0.5, 1.0], "{:.0%}".format, label_w=196)
        v = svc["src_vs_turns"]
        note = f"LongMemEval-s 60문항. 출처 회상이 새로 맞힌 문항 {v['benefit']}, 잃은 문항 {v['tax']}"
        fig.text(22, bottom + 8, note, "pf-note")
        y += height + 24
    return finish(fig, y)


def exp_loop_overflow(r: dict) -> Fig:
    d = r["loop_overflow"]
    gpt = d["models"]["gpt-4o-mini"]
    t, budget = d["max_turns"], d["resume_budget"]
    names = {
        "baseline": (f"이어가기 없음 ({t}차례)", "pf-s1"),
        "resume": (f"넘침 이어가기 ({t}+{budget}차례)", "pf-s3"),
        "unbounded": ("참고: 20차례", "pf-s2"),
    }
    keys = list(names)
    s = {k: gpt[k]["summary"] for k in keys}
    rows = [
        ("정답률 (공식 점수 평균)", {k: s[k]["accuracy"] for k in keys}),
        ("답을 낸 과제 비율", {k: s[k]["answered"] for k in keys}),
        ("예산을 넘긴 과제 비율", {k: s[k]["overflow_rate"] for k in keys}),
        ("넘친 뒤 모델 답으로 끝낸 비율", {k: s[k]["completed_after_overflow"] for k in keys}),
    ]
    fig = Fig("exp-loop-overflow", 0, "넘침 이어가기 전후, KramaBench 과제")
    note = f"gpt-4o-mini, archeology와 legal 과제 {s['resume']['tasks']}개, 과제당 LLM 호출 평균: " + ", ".join(
        f"{names[k][0].split(' (')[0]} {s[k]['mean_llm_calls']:.1f}" for k in keys
    )
    draw = bars_with_legend(fig, keys, rows, 1.0, UNIT, PCT, PCT, names, note, axis_title="비율")
    y = section(fig, 10, "정답률, 답 비율, 넘침과 넘친 뒤 완료", draw)
    buckets = [("1~6차례", 1, 6), ("7~9차례", 7, 9), ("10~19차례", 10, 19), ("20차례", 20, 20)]
    hist = [
        (label, {k: float(sum(lo <= n <= hi for n in s[k]["turns"])) for k in keys}) for label, lo, hi in buckets
    ]
    n = s["resume"]["tasks"]
    draw2 = bars_with_legend(fig, keys, hist, float(n), [0, n / 2, n], "{:.0f}", "{:.0f}", names,
                             axis_title="과제 수")
    y = section(fig, y, "과제별로 쓴 차례 수 분포", draw2)
    return finish(fig, y)


# 성찰 순서 비교의 구성과 🔔 누출 라벨
GATE_ARMS = {
    "think_first": "현재 (사고 뒤 decision)",
    "decision_first": "판정 먼저",
    "anchor": "판정 먼저 + 앵커",
    "anchor_facts": "판정 먼저 + 앵커 + 사실",
}
LEAK_KINDS = {
    "concrete_notice": ("구체 알림", "pf-s2"),
    "greeting_only": ("인사뿐", "pf-s3"),
    "restates_answer": ("답 재진술", "pf-s1"),
    "user_analysis_leak": ("분석문 누출", "pf-ok"),
    "unclear": ("불명", "pf-bar"),
}


def _ranged_bars(fig: Fig, x: float, y: float, w: float, rows: list, keys: list[str], names: dict) -> float:
    """막대는 반복 평균, 가로선은 반복 사이 최소와 최대다. 행마다 시리즈를 위아래로 쌓는다."""
    label_w = max(text_width(label, LABEL_FS) for label, _ in rows) + 22
    bar_w = w - label_w - VALUE_W - 30
    top = y
    for label, values in rows:
        group_h = len(keys) * (BAR_H + BAR_GAP) - BAR_GAP
        fig.text(x + label_w - 12, y + group_h / 2 + 4.5, label, "pf-lab", "end")
        for i, key in enumerate(keys):
            v, (lo, hi) = values[key]
            by = y + i * (BAR_H + BAR_GAP)
            bx = x + label_w
            fig.parts.append(
                f'<rect class="{names[key][1]}" x="{bx:.1f}" y="{by}" width="{max(bar_w * v, 1.5):.1f}"'
                f' height="{BAR_H}" rx="2"/>'
            )
            cy = by + BAR_H / 2
            fig.parts.append(
                f'<line class="pf-line--after" x1="{bx + bar_w * lo:.1f}" y1="{cy}" x2="{bx + bar_w * hi:.1f}" y2="{cy}"/>'
            )
            fig.text(bx + bar_w * max(v, hi) + 6, by + BAR_H - 1, f"{v:.2f}", "pf-val")
        y += group_h + ROW_GAP
    return axis(fig, x + label_w, top - 4, y - ROW_GAP + 4, bar_w, 1.0, UNIT, "{:.1f}", "비율, AUC (0~1)") + 8


def _stacked_kinds(fig: Fig, x: float, y: float, w: float, rows: list, kinds: dict) -> float:
    """행마다 라벨 건수를 비율로 이어 붙인 가로 막대. 칸 안에 건수를, 끝에 합계를 적는다."""
    label_w = max(text_width(label, LABEL_FS) for label, _ in rows) + 22
    bar_w = w - label_w - 40
    for label, counts in rows:
        total = sum(counts.get(k, 0) for k in kinds)
        fig.text(x + label_w - 12, y + BAR_H + 2, label, "pf-lab", "end")
        bx = x + label_w
        for key, (name, cls) in kinds.items():
            n = counts.get(key, 0)
            if not n:
                continue
            seg = bar_w * n / total
            fig.parts.append(
                f'<g><title>{label}, {name}: {n}</title><rect class="{cls}" x="{bx:.1f}" y="{y}"'
                f' width="{seg:.1f}" height="{BAR_H + 6}" rx="2"/></g>'
            )
            if seg > 18:
                text_cls = "pf-badge-t" if cls in ("pf-s2", "pf-s3", "pf-ok") else "pf-val"
                fig.text(bx + seg / 2, y + BAR_H + 1, str(n), text_cls, "middle")
            bx += seg
        fig.text(x + label_w + bar_w + 8, y + BAR_H + 1, f"{total}", "pf-axis")
        y += BAR_H + 6 + ROW_GAP
    return y


def exp_proactive_gate(r: dict) -> Fig:
    d = r["proactive_decision_first"]
    arms = [a for a in GATE_ARMS if a in d["arms"]]
    fig = Fig("exp-proactive-gate", 0, "성찰 순서: 사고 뒤 decision 과 판정 먼저, 앵커, 사실 계산")
    names = {
        "recall": ("recall (must)", "pf-s2"),
        "false_alarm": ("오경보 (must_not)", "pf-s3"),
        "auc": ("AUC (must 대 must_not)", "pf-s1"),
    }
    rows = [
        (
            f"{GATE_ARMS[a]} ({d['arms'][a]['test']['threshold']})",
            {k: (d["arms"][a]["test"][k], d["arms"][a]["test"][f"{k}_range"]) for k in names},
        )
        for a in arms
    ]

    def draw_a(y: float) -> float:
        legend(fig, 30, y + 2, list(names), names)
        return _ranged_bars(fig, 20, y + 26, WIDTH - 40, rows, list(names), names)

    y = section(fig, 10, "(a) 시험용 사례, 3회. 막대는 평균, 선은 최소와 최대. 괄호는 개발용에서 고른 임계치", draw_a)
    calls = {"llm": ("사고와 발화 LLM", "pf-s2"), "decision": ("decision model", "pf-s1")}
    call_rows = [
        (GATE_ARMS[a], {"llm": d["arms"][a]["test"]["llm_per_case"], "decision": d["arms"][a]["test"]["decision_per_case"]})
        for a in arms
    ]
    vmax = max(4.0, max(max(v.values()) for _, v in call_rows))
    draw_b = bars_with_legend(fig, list(calls), call_rows, vmax, [0, vmax / 2, vmax], "{:.0f}", "{:.2f}", calls,
                              axis_title="사례당 호출 수")
    y = section(fig, y, "(b) 사례당 호출 수", draw_b)
    leak_rows = [(GATE_ARMS[a], d["arms"][a]["leak_labels"]) for a in arms]

    def draw_c(y: float) -> float:
        legend(fig, 30, y + 2, list(LEAK_KINDS), LEAK_KINDS)
        bottom = _stacked_kinds(fig, 20, y + 26, WIDTH - 40, leak_rows, LEAK_KINDS)
        fig.text(30, bottom + 4, f"판정자 {d['judge']['model']}, 사람 라벨 {d['judge']['human']['status']}", "pf-note")
        return bottom + 12

    y = section(fig, y, "(c) 시험용에서 건넨 🔔 의 판정자 라벨", draw_c)
    return finish(fig, y)


FIGURES = [
    exp_mcp,
    exp_scheduling,
    exp_extension,
    exp_sessions,
    exp_orchestration,
    exp_architecture,
    exp_loop_overflow,
    exp_proactive,
    exp_proactive_gate,
    exp_inner_thought,
    exp_open_loop,
    exp_memory,
    exp_memory_recall,
    exp_memory_net_value,
    exp_approval,
    exp_voice,
    exp_team,
    exp_focus,
    exp_procedures,
]


def main() -> None:
    results = load()
    only = set(sys.argv[1:])
    for build in FIGURES:
        # 이름을 고르면 다른 그림은 만들지 않는다(다른 실험의 결과 키가 아직 없어도 돈다)
        if only and build.__name__.replace("_", "-") not in only:
            continue
        fig = build(results)
        (OUT_DIR / f"{fig.name}.svg").write_text(fig.svg())
        print(OUT_DIR / f"{fig.name}.svg")


if __name__ == "__main__":
    main()
