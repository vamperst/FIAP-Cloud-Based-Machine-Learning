#!/usr/bin/env python3
"""Evaluate the held-out test set through the deployed endpoint.

The test set is scored where it matters - across the network, through the same
serving path a caller would use - not in-process against a local model object.
That is the difference between "the model works" and "the system works".

Accuracy is reported next to the majority-class baseline on purpose: on a dataset
with ~34% positives, predicting "never churns" already scores ~66%.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1 import aws_helpers as aws
from lab1 import metrics as m
from lab1.config import (
    DATA_DIR,
    MODEL_TEST_FEATURES_FILE,
    TEST_LABELS_FILE,
    emit,
    evidence_dir,
    load_config,
    log,
)


def read_test_set(data: Path) -> tuple[list[str], list[int], list[int]]:
    with (data / MODEL_TEST_FEATURES_FILE).open(newline="", encoding="utf-8") as handle:
        rows = [",".join(row) for row in csv.reader(handle) if row]
    with (data / TEST_LABELS_FILE).open(newline="", encoding="utf-8") as handle:
        label_rows = [row for row in csv.reader(handle) if row][1:]
    ids = [int(row[0]) for row in label_rows]
    labels = [int(row[1]) for row in label_rows]
    if not (len(rows) == len(labels)):
        raise aws.AwsError(f"{len(rows)} feature rows but {len(labels)} labels - dataset is inconsistent")
    return rows, labels, ids


def cross_check_with_sklearn(labels: list[int], scores: list[float], report: dict) -> dict:
    """Independent second opinion on our own metric code."""
    try:
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
    except ImportError:
        return {"available": False}

    threshold = report["decision_threshold"]
    predictions = [1 if s >= threshold else 0 for s in scores]
    reference = {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, scores)),
    }
    deltas = {k: abs(reference[k] - report[k]) for k in reference}
    return {
        "available": True,
        "reference": {k: round(v, 6) for k, v in reference.items()},
        "max_absolute_delta": round(max(deltas.values()), 9),
        "agrees": all(d <= 1e-6 for d in deltas.values()),
    }


def to_markdown(result: dict) -> str:
    r = result["metrics"]
    cm = r["confusion_matrix"]
    accepted = result["acceptance"]
    lines = [
        "# Lab 1 - test-set evaluation",
        "",
        f"- Endpoint: `{result['endpoint_name']}`",
        f"- Samples: {r['samples']}",
        f"- Positive-class prevalence: {r['prevalence']:.4f}",
        f"- Decision threshold: {r['decision_threshold']} "
        "(fixed for teaching purposes, not a production choice)",
        f"- Requests sent: {result['requests_sent']} batches of up to {result['batch_size']} rows",
        "",
        "## Why accuracy alone is not the answer",
        "",
        f"| Predictor | Accuracy |",
        f"|---|---|",
        f"| Always predict the majority class | {r['majority_baseline_accuracy']:.4f} |",
        f"| Deployed model | {r['accuracy']:.4f} |",
        "",
        f"Lift over the baseline: **{r['accuracy_lift_over_baseline']:+.4f}**.",
        "",
        "## Confusion matrix",
        "",
        "| | Predicted 0 | Predicted 1 |",
        "|---|---|---|",
        f"| **Actual 0** | {cm['true_negative']} | {cm['false_positive']} |",
        f"| **Actual 1** | {cm['false_negative']} | {cm['true_positive']} |",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy | {r['accuracy']:.4f} |",
        f"| Precision | {r['precision']:.4f} |",
        f"| Recall | {r['recall']:.4f} |",
        f"| F1 | {r['f1']:.4f} |",
        f"| ROC-AUC | {r['roc_auc']:.4f} |",
        f"| PR-AUC | {r['pr_auc']:.4f} |",
        f"| Brier score | {r['brier_score']:.4f} |",
        "",
        "## Calibration (diagnostic)",
        "",
        "| Score band | Rows | Mean predicted | Observed rate |",
        "|---|---|---|---|",
    ]
    for row in r["calibration"]:
        predicted = f"{row['mean_predicted']:.4f}" if row["mean_predicted"] is not None else "-"
        observed = f"{row['observed_rate']:.4f}" if row["observed_rate"] is not None else "-"
        lines.append(f"| {row['bin']} | {row['count']} | {predicted} | {observed} |")

    lines += [
        "",
        "## Acceptance",
        "",
        "| Criterion | Threshold | Observed | Result |",
        "|---|---|---|---|",
    ]
    for name, check in accepted["checks"].items():
        lines.append(
            f"| {name} | {check['threshold']} | {check['observed']} "
            f"| {'PASS' if check['passed'] else 'FAIL'} |"
        )
    lines += [
        "",
        f"**Overall: {'PASS' if accepted['passed'] else 'FAIL'}**",
        "",
    ]
    check = result["sklearn_cross_check"]
    if check.get("available"):
        lines += [
            "## Metric cross-check",
            "",
            f"The lab's own metric implementations agree with scikit-learn "
            f"(max absolute difference {check['max_absolute_delta']:.2e}): "
            f"**{'yes' if check['agrees'] else 'no'}**.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--endpoint", help="defaults to the endpoint_name Terraform output")
    parser.add_argument("--data", type=Path, default=DATA_DIR)
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args()

    cfg = load_config()
    try:
        session = aws.make_session(cfg.region, args.profile)
        endpoint = args.endpoint or aws.require_output(aws.terraform_outputs(), "endpoint_name")

        status = aws.describe_endpoint(session, endpoint)["EndpointStatus"]
        if status != "InService":
            raise aws.AwsError(f"endpoint {endpoint} is {status}, not InService")

        rows, labels, ids = read_test_set(args.data)
        log(f"[evaluate] scoring {len(rows)} held-out rows through {endpoint}")

        scores: list[float] = []
        batches = 0
        for batch in aws.batched(rows, args.batch_size):
            scores.extend(aws.invoke_endpoint_csv(session, endpoint, "\n".join(batch)))
            batches += 1
            log(f"[evaluate] batch {batches}: {len(scores)}/{len(rows)} rows scored")

        if len(scores) != len(rows):
            raise aws.AwsError(f"{len(scores)} probabilities for {len(rows)} rows")
    except aws.AwsError as exc:
        log(f"[FAIL] {exc}")
        emit({"passed": False, "error": str(exc)})
        return 1

    report = m.evaluate(labels, scores, threshold=cfg.decision_threshold)
    acceptance = cfg.acceptance
    checks = {
        "roc_auc_min": {
            "threshold": acceptance["roc_auc_min"],
            "observed": report["roc_auc"],
            "passed": report["roc_auc"] >= acceptance["roc_auc_min"],
        },
        "f1_min": {
            "threshold": acceptance["f1_min"],
            "observed": report["f1"],
            "passed": report["f1"] >= acceptance["f1_min"],
        },
    }
    if acceptance.get("must_beat_majority_accuracy"):
        checks["beats_majority_accuracy"] = {
            "threshold": report["majority_baseline_accuracy"],
            "observed": report["accuracy"],
            "passed": report["beats_majority_baseline"],
        }

    result = {
        "endpoint_name": endpoint,
        "region": cfg.region,
        "samples": report["samples"],
        "batch_size": args.batch_size,
        "requests_sent": batches,
        "first_observation_id": ids[0],
        "last_observation_id": ids[-1],
        "metrics": report,
        "acceptance": {"checks": checks, "passed": all(c["passed"] for c in checks.values())},
        "sklearn_cross_check": cross_check_with_sklearn(labels, scores, report),
    }
    result["passed"] = result["acceptance"]["passed"] and result["sklearn_cross_check"].get(
        "agrees", True
    )

    out = evidence_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "evaluation.md").write_text(to_markdown(result), encoding="utf-8")

    log(f"[evaluate] majority baseline accuracy {report['majority_baseline_accuracy']:.4f}")
    log(f"[evaluate] accuracy {report['accuracy']:.4f} (lift {report['accuracy_lift_over_baseline']:+.4f})")
    log(f"[evaluate] precision {report['precision']:.4f} recall {report['recall']:.4f} f1 {report['f1']:.4f}")
    log(f"[evaluate] roc_auc {report['roc_auc']:.4f} pr_auc {report['pr_auc']:.4f}")
    for name, check in checks.items():
        log(f"  [{'PASS' if check['passed'] else 'FAIL'}] {name}: {check['observed']} vs {check['threshold']}")
    if result["sklearn_cross_check"].get("available"):
        log(f"  [{'PASS' if result['sklearn_cross_check']['agrees'] else 'FAIL'}] metrics agree with scikit-learn")
    log(f"[evaluate] wrote {out / 'evaluation.json'} and evaluation.md")

    emit(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
