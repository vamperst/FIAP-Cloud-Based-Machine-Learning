"""Metric unit tests with hand-computable cases.

Every expected value below can be checked with pencil and paper, which is the
point: the evaluation report is only trustworthy if the arithmetic behind it is.
"""

from __future__ import annotations

import math

import pytest

from lab1 import metrics as m

# 10 samples, 4 positives. Chosen so every metric has a distinct, tidy value.
Y_TRUE = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
Y_PRED = [1, 1, 1, 0, 1, 0, 0, 0, 0, 0]
# tp=3 fn=1 fp=1 tn=5


def test_confusion_matrix_counts_each_quadrant():
    cm = m.confusion_matrix(Y_TRUE, Y_PRED)
    assert (cm.true_positive, cm.false_negative, cm.false_positive, cm.true_negative) == (3, 1, 1, 5)


def test_accuracy_precision_recall_f1_by_hand():
    cm = m.confusion_matrix(Y_TRUE, Y_PRED)
    assert m.accuracy(cm) == pytest.approx(8 / 10)
    assert m.precision(cm) == pytest.approx(3 / 4)
    assert m.recall(cm) == pytest.approx(3 / 4)
    assert m.f1(cm) == pytest.approx(3 / 4)


def test_f1_is_the_harmonic_mean_not_the_average():
    cm = m.ConfusionMatrix(true_negative=90, false_positive=0, false_negative=8, true_positive=2)
    assert m.precision(cm) == pytest.approx(1.0)
    assert m.recall(cm) == pytest.approx(0.2)
    assert m.f1(cm) == pytest.approx(2 * 1.0 * 0.2 / 1.2)
    assert m.f1(cm) < (1.0 + 0.2) / 2


def test_perfect_and_inverted_separation():
    labels = [0, 0, 1, 1]
    assert m.roc_auc(labels, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert m.roc_auc(labels, [0.9, 0.8, 0.2, 0.1]) == pytest.approx(0.0)


def test_all_scores_tied_gives_a_coin_flip():
    assert m.roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.5)


def test_roc_auc_handles_partial_ties_with_average_ranks():
    # One tie straddling the classes: 1 clean win, 1 tie counted as half.
    assert m.roc_auc([0, 1, 0, 1], [0.2, 0.4, 0.4, 0.9]) == pytest.approx(0.875)


def test_roc_auc_equals_the_probability_of_correct_ranking():
    labels = [0, 0, 0, 1, 1]
    scores = [0.1, 0.4, 0.35, 0.8, 0.3]
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives
    )
    assert m.roc_auc(labels, scores) == pytest.approx(wins / (len(positives) * len(negatives)))


def test_roc_auc_needs_both_classes():
    with pytest.raises(ValueError, match="one class"):
        m.roc_auc([1, 1, 1], [0.2, 0.5, 0.9])


def test_roc_auc_rejects_non_binary_labels():
    with pytest.raises(ValueError, match="binary"):
        m.roc_auc([0, 1, 2], [0.1, 0.2, 0.3])


def test_average_precision_on_a_hand_case():
    # Ranked: 0.9(pos) 0.6(neg) 0.4(pos) -> (1/1 + 2/3) / 2
    value = m.average_precision([1, 0, 1], [0.9, 0.6, 0.4])
    assert value == pytest.approx((1.0 + 2 / 3) / 2)


def test_brier_score_penalises_confident_mistakes():
    assert m.brier_score([1], [1.0]) == pytest.approx(0.0)
    assert m.brier_score([1], [0.0]) == pytest.approx(1.0)


def test_majority_baseline_is_the_bar_to_beat():
    assert m.majority_baseline_accuracy([1] * 3 + [0] * 7) == pytest.approx(0.7)
    assert m.majority_baseline_accuracy([1] * 7 + [0] * 3) == pytest.approx(0.7)
    assert m.prevalence([1] * 3 + [0] * 7) == pytest.approx(0.3)


def test_evaluate_reports_the_baseline_next_to_accuracy():
    scores = [0.9, 0.8, 0.7, 0.4, 0.6, 0.3, 0.2, 0.1, 0.05, 0.02]
    report = m.evaluate(Y_TRUE, scores, threshold=0.5)
    assert report["samples"] == 10
    assert report["prevalence"] == pytest.approx(0.4)
    assert report["majority_baseline_accuracy"] == pytest.approx(0.6)
    assert report["accuracy"] == pytest.approx(0.8)
    assert report["beats_majority_baseline"] is True
    assert report["accuracy_lift_over_baseline"] == pytest.approx(0.2)
    assert set(report["confusion_matrix"]) == {
        "true_negative",
        "false_positive",
        "false_negative",
        "true_positive",
    }


def test_evaluate_exposes_an_accurate_but_useless_model():
    """95% accuracy, zero recall: the lesson the lab is built around."""
    labels = [0] * 95 + [1] * 5
    scores = [0.01] * 100
    report = m.evaluate(labels, scores, threshold=0.5)
    assert report["accuracy"] == pytest.approx(0.95)
    assert report["recall"] == pytest.approx(0.0)
    assert report["f1"] == pytest.approx(0.0)
    assert report["beats_majority_baseline"] is False


def test_threshold_changes_the_confusion_matrix_not_the_auc():
    labels = [0, 0, 1, 1]
    scores = [0.2, 0.45, 0.55, 0.8]
    strict = m.evaluate(labels, scores, threshold=0.5)
    loose = m.evaluate(labels, scores, threshold=0.3)
    assert strict["roc_auc"] == loose["roc_auc"]
    assert loose["confusion_matrix"]["false_positive"] > strict["confusion_matrix"]["false_positive"]


def test_calibration_bins_cover_the_unit_interval():
    labels = [0, 1] * 10
    scores = [i / 19 for i in range(20)]
    bins = m.calibration_bins(labels, scores, bins=5)
    assert len(bins) == 5
    assert sum(b["count"] for b in bins) == 20


def test_metrics_reject_mismatched_lengths():
    with pytest.raises(ValueError, match="length mismatch"):
        m.roc_auc([0, 1], [0.5])


def test_metrics_reject_non_finite_scores():
    with pytest.raises(ValueError, match="non-finite"):
        m.roc_auc([0, 1], [0.5, math.inf])


def test_our_metrics_agree_with_scikit_learn():
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    labels = [0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0]
    scores = [0.1, 0.9, 0.4, 0.35, 0.8, 0.2, 0.55, 0.65, 0.05, 0.7, 0.45, 0.3]
    predictions = [1 if s >= 0.5 else 0 for s in scores]
    cm = m.confusion_matrix(labels, predictions)

    assert m.accuracy(cm) == pytest.approx(sklearn_metrics.accuracy_score(labels, predictions))
    assert m.precision(cm) == pytest.approx(sklearn_metrics.precision_score(labels, predictions))
    assert m.recall(cm) == pytest.approx(sklearn_metrics.recall_score(labels, predictions))
    assert m.f1(cm) == pytest.approx(sklearn_metrics.f1_score(labels, predictions))
    assert m.roc_auc(labels, scores) == pytest.approx(sklearn_metrics.roc_auc_score(labels, scores))
    assert m.average_precision(labels, scores) == pytest.approx(
        sklearn_metrics.average_precision_score(labels, scores)
    )
    assert m.brier_score(labels, scores) == pytest.approx(
        sklearn_metrics.brier_score_loss(labels, scores)
    )
