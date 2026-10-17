"""Draws the performance-experiment charts on the docs feature pages from scripts/experiments/results.json."""

import json
import sys
from pathlib import Path

from scripts.docs_figures import OUT_DIR, WIDTH, Fig, text_width

RESULTS = Path(__file__).resolve().parent / "experiments" / "results.json"
LABEL_W = 150
BAR_H = 10
BAR_GAP = 3
ROW_GAP = 12
SERIES = {"e2b": ("gemma4:e2b", "pf-s1"), "e4b": ("gemma4:e4b", "pf-s2"), "gpt": ("gpt-4o-mini", "pf-s3")}


def legend(fig: Fig, x: float, y: float, keys: list[str], names: dict[str, tuple[str, str]] = SERIES) -> None:
    for key in keys:
        name, cls = names[key]
        fig.parts.append(f'<rect class="{cls}" x="{x}" y="{y - 8}" width="10" height="10" rx="2"/>')
        fig.text(x + 15, y + 1, name, "pf-s")
        x += 15 + text_width(name, 11) + 18


def axis(fig: Fig, x0: float, y0: float, y1: float, w: float, vmax: float, ticks: list[float], fmt: str) -> None:
    for t in ticks:
        tx = x0 + w * t / vmax
        fig.parts.append(f'<line class="pf-grid" x1="{tx:.1f}" y1="{y0}" x2="{tx:.1f}" y2="{y1}"/>')
        fig.text(tx, y1 + 13, fmt.format(t), "pf-axis", "middle")


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
) -> float:
    """가로 막대 묶음. 행마다 시리즈 막대를 위아래로 쌓고 끝에 값을 적는다. 그린 뒤의 y 를 돌려준다."""
    bar_w = w - LABEL_W - 44
    top = y
    for label, values in rows:
        group_h = len(keys) * (BAR_H + BAR_GAP) - BAR_GAP
        fig.text(x + LABEL_W - 10, y + group_h / 2 + 4, label, "pf-s", "end")
        for i, key in enumerate(keys):
            v = values.get(key)
            by = y + i * (BAR_H + BAR_GAP)
            if v is None:
                fig.text(x + LABEL_W + 4, by + BAR_H - 1, "측정 안 함", "pf-axis")
                continue
            bw = max(bar_w * min(v, vmax) / vmax, 1.5)
            fig.parts.append(
                f'<rect class="{names[key][1]}" x="{x + LABEL_W}" y="{by}" width="{bw:.1f}" height="{BAR_H}" rx="2"/>'
            )
            fig.text(x + LABEL_W + bw + 5, by + BAR_H - 1, val_fmt.format(v), "pf-val")
        y += group_h + ROW_GAP
    axis(fig, x + LABEL_W, top - 4, y - ROW_GAP + 4, bar_w, vmax, ticks, fmt)
    return y + 14


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


def bars_with_legend(fig, keys, rows, vmax, ticks, fmt="{:.1f}", val_fmt="{:.2f}", names=SERIES, note=""):  # type: ignore[no-untyped-def]
    def draw(y: float) -> float:
        legend(fig, 30, y + 2, keys, names)
        bottom = grouped_bars(fig, 20, y + 24, WIDTH - 40, rows, keys, vmax, ticks, fmt, val_fmt, names)
        if note:
            fig.text(30, bottom + 4, note, "pf-note")
            bottom += 14
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
    rows = [
        (f"{c['label']} ({c['threshold']})", {"recall": c["recall"], "fa": c["false_alarm"]}) for c in cmp["test"]
    ]
    draw = bars_with_legend(fig, list(names), rows, 1.0, UNIT, names=names)
    y = section(fig, 10, "(a) 블라인드 시험 상황 20개 × 3회. 괄호는 개발용에서 고른 확신도 임계치", draw)
    rows = [("정확도", {k: rep[k]["accuracy"] for k in MODELS})]
    y = section(fig, y, "(b) 🔔 뒤 짧은 답 12개 × 3회 분류 정확도", bars_with_legend(fig, MODELS, rows, 1.0, UNIT))
    return finish(fig, y)


def exp_inner_thought(r: dict) -> Fig:
    t, fr = r["thought_timing"], r["thought_frames"]
    names = {"local": ("로컬 e4b + e2b", "pf-s2"), "cloud": ("gpt-4o-mini", "pf-s3")}
    fig = Fig("exp-inner-thought", 0, "사고 시점별 응답 속도와 요청 사고 품질")
    rows = []
    for mode in ("before", "race", "after"):
        rows.append((f"{mode} · 첫 글자", {k: t[k][mode]["first"] for k in names}))
        rows.append((f"{mode} · 응답 끝", {k: t[k][mode]["total"] for k in names}))
    draw = bars_with_legend(fig, list(names), rows, 25, [0, 5, 10, 15, 20, 25], "{:.0f}", "{:.1f}s", names)
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
        bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note),
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
            fig.text(x0 - 12, y + 4, name, "pf-s", "end")
            acc = f"판정 정확도 {data['same_loop_acc']:.2f}, 잘못 합침 {data['false_merge']}"
            fig.text(x0 - 12, y + 18, acc, "pf-axis", "end")
            for p in data["pairs"]:
                px = x0 + w * (p["cos"] - lo) / (hi - lo)
                if p["same"]:
                    fig.parts.append(f'<circle class="pf-dot-same" cx="{px:.1f}" cy="{y - 2}" r="4"/>')
                else:
                    fig.parts.append(
                        f'<rect class="pf-dot-diff" x="{px - 3.5:.1f}" y="{y + 5}" width="7" height="7" '
                        f'transform="rotate(45 {px:.1f} {y + 8.5})"/>'
                    )
            y += 48
        bottom = y - 20
        for tick in [t / 10 for t in range(int((lo + 0.05) * 10), 11)]:
            tx = x0 + w * (tick - lo) / (hi - lo)
            fig.parts.append(f'<line class="pf-grid" x1="{tx:.1f}" y1="{top}" x2="{tx:.1f}" y2="{bottom}"/>')
            fig.text(tx, bottom + 13, f"{tick:.1f}", "pf-axis", "middle")
        rx = x0 + w * (0.85 - lo) / (hi - lo)
        fig.parts.append(f'<line class="pf-ref" x1="{rx:.1f}" y1="{top}" x2="{rx:.1f}" y2="{bottom}"/>')
        fig.text(rx + 4, top + 8, "문턱 0.85", "pf-ref-t")
        if plain:
            acc, merges = plain["same_loop_acc"], plain["false_merge"]
            note = f"임베딩 없이 글자 규칙만 쓰면 판정 정확도 {acc:.2f}, 잘못 합침 {merges}"
            fig.text(30, bottom + 34, note, "pf-note")
            return bottom + 40
        return bottom + 20

    y = section(fig, 10, "약속 18쌍의 코사인: 바꿔 말한 같은 약속(●)과 같은 주제의 다른 약속(◆)", draw)
    return finish(fig, y)


def exp_memory(r: dict) -> Fig:
    lang = r["summary_language"]
    fig = Fig("exp-memory", 0, "컴팩션 요약의 언어와 사실 보존")

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
    draw = bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note)
    y = section(fig, 10, "한국어 대화 3개 × 3회 요약, 심어 둔 사실 12개", draw)
    return finish(fig, y)


def check_matrix(fig: Fig, x: float, y: float, cols: list[str], rows: list[tuple[str, list[str]]]) -> float:
    """단계 × 지표 준수표. 전부 지키면 채운 원, 일부면 지킨 비율만큼 채운 원, 하나도 못 지키면 빨간 빈 원이다."""
    col_w = (WIDTH - x - 40 - 230) / len(cols)
    for i, c in enumerate(cols):
        fig.text(x + 230 + col_w * (i + 0.5), y, c, "pf-s", "middle")
    y += 24
    for label, cells in rows:
        fig.text(x + 220, y + 4, label, "pf-s", "end")
        for i, cell in enumerate(cells):
            cx = x + 230 + col_w * (i + 0.5)
            if "/" in cell:
                a, b = (int(n) for n in cell.split("/"))
                cls = "pf-ok" if a == b else ("pf-part" if a else "pf-zero")
                fig.parts.append(f'<circle class="{cls}" cx="{cx - 18:.1f}" cy="{y}" r="6"/>')
                if 0 < a < b:
                    # 일부만 지켰으면 지킨 비율만큼 원을 채운다(아래에서 위로)
                    fill_h = 12 * a / b
                    clip = f"{fig.name}-c{len(fig.parts)}"
                    box = f'<rect x="{cx - 24:.1f}" y="{y + 6 - fill_h:.1f}" width="12" height="{fill_h:.1f}"/>'
                    fig.parts.append(f'<clipPath id="{clip}">{box}</clipPath>')
                    fig.parts.append(
                        f'<circle class="pf-ok" cx="{cx - 18:.1f}" cy="{y}" r="6" clip-path="url(#{clip})"/>'
                    )
                fig.text(cx - 6, y + 4, cell, "pf-val")
            else:
                fig.text(cx, y + 4, cell, "pf-axis", "middle")
        y += 26
    return y - 10


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
    draw = bars_with_legend(fig, MODELS, rows, 1.0, UNIT, note=note)
    y = section(fig, y, "(b) 승인 답 12개 × 3회, 분류기 단독(키워드 단계 없이)", draw)
    return finish(fig, y)


def exp_voice(r: dict) -> Fig:
    p = r["piper"]
    names = {"audio": ("음성 길이", "pf-s1"), "synth": ("합성 시간", "pf-s3")}
    fig = Fig("exp-voice", 0, "Piper 영어 음성 합성 시간과 음성 길이")
    rows = [(f"{s['chars']}자 문장", {"audio": s["audio_s"], "synth": s["synth_s"]}) for s in p]
    draw = bars_with_legend(fig, list(names), rows, 7, list(range(8)), "{:.0f}", "{:.2f}s", names)
    y = section(fig, 10, "Piper(high) 합성, 컨테이너 CPU 14코어: 합성 시간은 음성 길이의 약 1/5", draw)
    return finish(fig, y)


def exp_team(r: dict) -> Fig:
    d = r["delegation"]
    names = {"local": ("gemma4:e4b (두 에이전트)", "pf-s2"), "cloud": ("gpt-4o-mini (두 에이전트)", "pf-s3")}
    fig = Fig("exp-team", 0, "JARVIS 가 KAREN 에게 맡기는 위임 실험")
    rows = [("위임 한 번", {k: d[k]["total_s"] for k in names})]
    note = "ask_agent 사용 3/3, KAREN 의 sh_notice 호출 3/3 (두 모델 모두)"
    draw = bars_with_legend(fig, list(names), rows, 40, [0, 10, 20, 30, 40], "{:.0f}", "{:.1f}s", names, note)
    y = section(fig, 10, "청약 공고 찾기 위임 3회: 끝까지 걸린 시간(초, 중앙값)", draw)
    return finish(fig, y)


def exp_focus(r: dict) -> Fig:
    f = r["focus"]
    names = {"local": ("gemma4:e4b", "pf-s2"), "cloud": ("gpt-4o-mini", "pf-s3")}
    fig = Fig("exp-focus", 0, "Focus 시작 시간과 조사 형식 준수")
    rows = [(t["task"], {"local": t["local"], "cloud": t["cloud"]}) for t in f["first_reply"]]
    draw = bars_with_legend(fig, list(names), rows, 45, [0, 15, 30, 45], "{:.0f}", "{:.1f}s", names)
    y = section(fig, 10, "(a) /focus 부터 첫 응답 글자까지(초), 작업 2개", draw)
    cols = ["gemma4:e4b", "gpt-4o-mini"]
    y = section(
        fig,
        y,
        "(b) 조사 결과가 지시문 형식을 지켰는가",
        lambda y0: check_matrix(fig, 20, y0 + 4, cols, [(row["rule"], row["cells"]) for row in f["reference"]]),
    )
    return finish(fig, y)


FIGURES = [exp_proactive, exp_inner_thought, exp_open_loop, exp_memory, exp_approval, exp_voice, exp_team, exp_focus]


def main() -> None:
    results = load()
    only = set(sys.argv[1:])
    for build in FIGURES:
        fig = build(results)
        if only and fig.name not in only:
            continue
        (OUT_DIR / f"{fig.name}.svg").write_text(fig.svg())
        print(OUT_DIR / f"{fig.name}.svg")


if __name__ == "__main__":
    main()
