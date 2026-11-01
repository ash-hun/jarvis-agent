"""proactive_eval 의 label_metrics: must 재현율, must_not 오경보, must 대 must_not AUC."""

from jarvis.core.proactive.eval.label_metrics import auc_must, false_alarm_must_not, recall_must

LABELS = ["must", "must", "can", "must_not", "must_not"]


def test_recall_and_false_alarm_ignore_can() -> None:
    spoke = [True, False, True, True, False]

    assert recall_must(LABELS, spoke) == 0.5
    assert false_alarm_must_not(LABELS, spoke) == 0.5


def test_recall_and_false_alarm_are_none_without_their_label() -> None:
    assert recall_must(["can"], [True]) is None
    assert false_alarm_must_not(["must"], [True]) is None


def test_auc_counts_ties_as_half_and_missing_scores_as_zero() -> None:
    assert auc_must(LABELS, [0.9, 0.5, 0.0, 0.5, None]) == 0.875
    assert auc_must(["must", "must_not"], [0.1, 0.9]) == 0.0


def test_auc_is_none_without_both_sides() -> None:
    assert auc_must(["must", "can"], [0.9, 0.1]) is None
