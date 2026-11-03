"""발화 시트 일치율: 다섯 라벨 행만 읽고, 사람과 판정자를 라벨별로 비교한다."""

from pathlib import Path
from scripts.experiments import proactive_decision_first as pdf

from jarvis.core.proactive.eval.utterance_judge import UtteranceVerdict


def _verdict(label: str) -> UtteranceVerdict:
    return UtteranceVerdict(label=label, evidence="")  # type: ignore[arg-type]


def test_labeled_rows_keeps_only_the_five_labels(tmp_path: Path) -> None:
    sheet = tmp_path / "s.csv"
    sheet.write_text("id,utterance,last_answer,human_label,human_note\ns1,a,,concrete_notice,x\ns2,b,,오타,\ns3,c,,,\n",
                     encoding="utf-8")
    assert [r["id"] for r in pdf.labeled_rows(sheet)] == ["s1"]
    assert pdf.labeled_rows(tmp_path / "none.csv") == []


def test_human_agreement_reports_per_label_and_waits_for_enough_rows() -> None:
    rows = [{"human_label": "greeting_only"}] * 10 + [{"human_label": "unclear"}] * 10
    verdicts = [_verdict("greeting_only")] * 10 + [_verdict("concrete_notice")] * 5 + [None] * 5

    out = pdf.human_agreement(rows, verdicts)

    assert out["status"] == "검증됨" and out["human_labels"] == {"greeting_only": 10, "unclear": 10}
    assert out["agreement"]["greeting_only"] == 1.0 and out["agreement"]["unclear"] == 0.0
    assert pdf.human_agreement(rows[:19], verdicts[:19]) == {"status": "검증 전", "labeled": 19}
