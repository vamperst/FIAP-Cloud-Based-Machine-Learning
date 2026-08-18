#!/usr/bin/env python3
"""Assemble the evidence package.

The central claim of the first class is that "correct" is a chain of evidence,
not a single metric. This script materialises that chain into one file: which
data (by hash), which image, which hyperparameters, which job, which artifact
(by size and ETag), which endpoint, which smoke result, which test metrics - and
which tool versions produced all of it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1 import aws_helpers as aws
from lab1.config import (
    DATA_DIR,
    MANIFEST_FILE,
    MODEL_TRAIN_FILE,
    MODEL_VALIDATION_FILE,
    emit,
    evidence_dir,
    load_config,
    log,
)


def run_capture(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, check=True, timeout=60
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip()


def git_state(repo: Path) -> dict[str, str | bool | None]:
    sha = run_capture(["git", "rev-parse", "HEAD"], cwd=repo)
    status = run_capture(["git", "status", "--porcelain"], cwd=repo)
    return {
        "commit_sha": sha,
        "branch": run_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo),
        "working_tree_clean": (status == "") if status is not None else None,
    }


def tool_versions(terraform_dir: Path) -> dict[str, object]:
    terraform_version: object = None
    raw = run_capture(["terraform", "version", "-json"], cwd=terraform_dir)
    if raw:
        parsed = json.loads(raw)
        terraform_version = {
            "terraform": parsed.get("terraform_version"),
            "providers": parsed.get("provider_selections", {}),
        }
    versions: dict[str, object] = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "terraform": terraform_version,
    }
    for module in ("boto3", "botocore", "numpy", "sklearn", "pytest"):
        try:
            versions[module] = __import__(module).__version__
        except Exception:  # a missing optional tool must not break the report
            versions[module] = None
    return versions


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def channel_evidence(session, outputs: dict, data_dir: Path) -> dict[str, object]:
    """HeadObject each training channel and compare its size with the local file.

    "The apply succeeded" says nothing about what SageMaker will read. This is the
    storage boundary proven at the object level: the bytes are there, and they are
    the same count of bytes the generator wrote.
    """
    local = {"train": MODEL_TRAIN_FILE, "validation": MODEL_VALIDATION_FILE}
    channels = outputs.get("training_channels")
    proven: dict[str, object] = {}
    if not isinstance(channels, dict):
        return proven

    for name, uri in channels.items():
        object_uri = f"{str(uri).rstrip('/')}/{name}.csv"
        bucket, key = aws.split_s3_uri(object_uri)
        head = aws.object_exists(session, bucket, key)
        local_name = local.get(name)
        local_path = data_dir / local_name if local_name else None
        local_bytes = local_path.stat().st_size if local_path and local_path.exists() else None
        proven[name] = {
            "uri": object_uri,
            "exists": bool(head),
            "remote_bytes": (head or {}).get("content_length"),
            "etag": (head or {}).get("etag"),
            "local_bytes": local_bytes,
            "size_matches_local": bool(head)
            and local_bytes is not None
            and head.get("content_length") == local_bytes,
        }
    return proven


def to_markdown(evidence: dict) -> str:
    dataset = evidence["dataset"]
    training = evidence.get("training") or {}
    smoke = evidence.get("smoke") or {}
    evaluation = evidence.get("evaluation") or {}
    metrics = evaluation.get("metrics") or {}
    endpoint = evidence.get("endpoint") or {}

    def row(label: str, value: object) -> str:
        return f"| {label} | {'-' if value in (None, '', {}) else value} |"

    lines = [
        "# Lab 1 - evidence package",
        "",
        f"Generated at {evidence['generated_at_utc']} UTC.",
        "",
        "A model is not an ML system. Below is the chain that turns one into the",
        "other, each link recorded with something checkable.",
        "",
        "## 1. Environment",
        "",
        "| Item | Value |",
        "|---|---|",
        row("AWS account", evidence["aws"]["account_id"]),
        row("Region", evidence["aws"]["region"]),
        row("Caller", evidence["aws"]["caller_arn"]),
        row("Execution role", evidence["aws"]["execution_role_arn"]),
        row("Git commit", evidence["git"]["commit_sha"]),
        row("Working tree clean", evidence["git"]["working_tree_clean"]),
        row("Terraform", (evidence["versions"].get("terraform") or {}).get("terraform")),
        row("AWS provider", (evidence["versions"].get("terraform") or {}).get("providers")),
        row("Python", evidence["versions"]["python"]),
        row("boto3 / botocore", f"{evidence['versions']['boto3']} / {evidence['versions']['botocore']}"),
        row("numpy / scikit-learn", f"{evidence['versions']['numpy']} / {evidence['versions']['sklearn']}"),
        "",
        "## 2. Data (storage capability)",
        "",
        "| Item | Value |",
        "|---|---|",
        row("Bucket", evidence["aws"]["bucket_name"]),
        row("Seed", dataset.get("seed")),
        row("Schema version", dataset.get("schema_version")),
        row("Rows", dataset.get("rows")),
        row("Source prevalence", (dataset.get("source") or {}).get("prevalence")),
        "",
        "| File | Rows | SHA-256 |",
        "|---|---|---|",
        f"| {(dataset.get('source') or {}).get('file')} | "
        f"{(dataset.get('source') or {}).get('rows')} | "
        f"`{(dataset.get('source') or {}).get('sha256')}` |",
    ]
    for name, split in (dataset.get("splits") or {}).items():
        lines.append(f"| {split.get('file')} ({name}) | {split.get('rows')} | `{split.get('sha256')}` |")

    channels_proven = evidence["aws"].get("input_channels") or {}
    if channels_proven:
        lines += [
            "",
            "Training channels as they exist in S3 (HeadObject, not inference):",
            "",
            "| Channel | Object | Bytes in S3 | Matches local file |",
            "|---|---|---|---|",
        ]
        for name, channel in sorted(channels_proven.items()):
            lines.append(
                f"| {name} | `{channel.get('uri')}` | {channel.get('remote_bytes')} | "
                f"{channel.get('size_matches_local')} |"
            )

    lines += [
        "",
        "## 3. Training (training capability)",
        "",
        "| Item | Value |",
        "|---|---|",
        row("Training job", training.get("training_job_name")),
        row("Status", training.get("status")),
        row("Start", training.get("training_start_time")),
        row("End", training.get("training_end_time")),
        row("Billable seconds", training.get("billable_seconds")),
        row("Image", training.get("training_image")),
        row("Input mode", training.get("training_input_mode")),
        row("Instance", f"{training.get('instance_count')} x {training.get('instance_type')}"),
        row("Volume (GB)", training.get("volume_size_in_gb")),
        row("Max runtime (s)", training.get("max_runtime_in_seconds")),
        row("Output path", training.get("output_s3_path")),
        "",
        "Hyperparameters as accepted by SageMaker:",
        "",
        "| Name | Value |",
        "|---|---|",
    ]
    for key, value in sorted((training.get("hyperparameters") or {}).items()):
        lines.append(f"| {key} | {value} |")

    lines += ["", "Input channels:", "", "| Channel | S3 URI | Content type |", "|---|---|---|"]
    for channel in training.get("input_channels") or []:
        lines.append(f"| {channel['channel']} | `{channel['s3_uri']}` | {channel['content_type']} |")

    if training.get("final_metrics"):
        lines += ["", "Metrics reported by the training container:", "", "| Metric | Value |", "|---|---|"]
        for metric in training["final_metrics"]:
            lines.append(f"| {metric['name']} | {metric['value']} |")

    lines += [
        "",
        "## 4. Model artifact",
        "",
        "| Item | Value |",
        "|---|---|",
        row("Artifact URI", f"`{training.get('model_artifact_uri')}`" if training.get("model_artifact_uri") else None),
        row("Size (bytes)", training.get("model_artifact_bytes")),
        row("ETag", training.get("model_artifact_etag")),
        row("Existence proven by", "s3:HeadObject before the Model was created"),
        "",
        "## 5. Serving (prediction capability)",
        "",
        "| Item | Value |",
        "|---|---|",
        row("SageMaker model", evidence["terraform_outputs"].get("model_name")),
        row("Endpoint config", evidence["terraform_outputs"].get("endpoint_config_name")),
        row("Endpoint", evidence["terraform_outputs"].get("endpoint_name")),
        row("Endpoint status", endpoint.get("status")),
        row("Instance", f"{endpoint.get('instance_count')} x {endpoint.get('instance_type')}"),
        "",
        "Deterministic smoke request:",
        "",
        "| Record | CSV payload | p(churn) |",
        "|---|---|---|",
    ]
    probabilities = smoke.get("probabilities") or {}
    for request in smoke.get("requests") or []:
        lines.append(f"| {request['name']} | `{request['csv']}` | {probabilities.get(request['name'])} |")
    if smoke:
        lines += [
            "",
            f"Smoke checks: **{'PASS' if smoke.get('passed') else 'FAIL'}** "
            f"({sum(1 for v in (smoke.get('checks') or {}).values() if v)}"
            f"/{len(smoke.get('checks') or {})}).",
        ]

    lines += [
        "",
        "## 6. Evaluation (evidence capability)",
        "",
        "| Item | Value |",
        "|---|---|",
        row("Samples", metrics.get("samples")),
        row("Prevalence", metrics.get("prevalence")),
        row("Decision threshold", metrics.get("decision_threshold")),
        row("Majority baseline accuracy", metrics.get("majority_baseline_accuracy")),
        row("Accuracy", metrics.get("accuracy")),
        row("Precision", metrics.get("precision")),
        row("Recall", metrics.get("recall")),
        row("F1", metrics.get("f1")),
        row("ROC-AUC", metrics.get("roc_auc")),
        row("PR-AUC", metrics.get("pr_auc")),
        row("Beats baseline", metrics.get("beats_majority_baseline")),
        "",
    ]
    if metrics.get("confusion_matrix"):
        cm = metrics["confusion_matrix"]
        lines += [
            "| | Predicted 0 | Predicted 1 |",
            "|---|---|---|",
            f"| **Actual 0** | {cm['true_negative']} | {cm['false_positive']} |",
            f"| **Actual 1** | {cm['false_negative']} | {cm['true_positive']} |",
            "",
        ]

    lines += [
        "## 7. Verdict",
        "",
        "| Stage | Result |",
        "|---|---|",
    ]
    for stage, passed in evidence["chain"].items():
        lines.append(f"| {stage} | {'PASS' if passed else 'MISSING/FAIL'} |")
    lines += ["", f"**Chain complete: {'yes' if evidence['passed'] else 'no'}**", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--data", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    cfg = load_config()
    out = evidence_dir()
    out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]

    outputs: dict[str, object] = {}
    aws_block: dict[str, object] = {"region": cfg.region}
    endpoint_block: dict[str, object] = {}

    try:
        session = aws.make_session(cfg.region, args.profile)
        identity = aws.whoami(session)
        aws_block.update(
            {"account_id": identity["account_id"], "caller_arn": identity["arn"]}
        )
        outputs = aws.terraform_outputs()
        aws_block["bucket_name"] = outputs.get("bucket_name")
        aws_block["execution_role_arn"] = outputs.get("execution_role_arn")
        aws_block["input_channels"] = channel_evidence(session, outputs, args.data)

        endpoint_name = outputs.get("endpoint_name")
        if endpoint_name:
            description = aws.describe_endpoint(session, str(endpoint_name))
            variant = (description.get("ProductionVariants") or [{}])[0]
            endpoint_block = {
                "status": description.get("EndpointStatus"),
                "arn": description.get("EndpointArn"),
                "created_at": aws.json_safe(description.get("CreationTime")),
                "variant_name": variant.get("VariantName"),
                "instance_type": outputs.get("instance_type"),
                "instance_count": variant.get("CurrentInstanceCount"),
            }
    except aws.AwsError as exc:
        # Evidence is still worth producing without live AWS access - it just
        # records that the serving links are missing.
        log(f"[warn] AWS/Terraform context unavailable: {exc}")

    dataset = load_json(args.data / MANIFEST_FILE) or {}
    training = load_json(out / "training_job.json")
    smoke = load_json(out / "smoke_prediction.json")
    evaluation = load_json(out / "evaluation.json")

    channels = aws_block.get("input_channels") or {}
    chain = {
        "storage: dataset generated and fingerprinted": bool(dataset),
        "storage: training channels proven in S3": bool(channels)
        and all(bool(c.get("size_matches_local")) for c in channels.values()),
        "training: job reached Completed": (training or {}).get("status") == "Completed",
        "artifact: model.tar.gz proven in S3": bool((training or {}).get("model_artifact_bytes")),
        "serving: endpoint InService": endpoint_block.get("status") == "InService",
        "serving: deterministic smoke inference passed": bool((smoke or {}).get("passed")),
        "evidence: test-set metrics meet acceptance": bool((evaluation or {}).get("passed")),
    }

    evidence = {
        "generated_at_utc": aws.utc_now_iso(),
        "lab": "lab1-model-to-ml-system",
        "schema_version": cfg.schema_version,
        "aws": aws_block,
        "git": git_state(repo_root),
        "versions": tool_versions(repo_root / "terraform"),
        "terraform_outputs": outputs,
        "dataset": dataset,
        "training": training,
        "endpoint": endpoint_block,
        "smoke": smoke,
        "evaluation": evaluation,
        "chain": chain,
        "passed": all(chain.values()),
    }

    (out / "evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "evidence.md").write_text(to_markdown(evidence), encoding="utf-8")

    for stage, passed in chain.items():
        log(f"  [{'PASS' if passed else 'FAIL'}] {stage}")
    log(f"[{'PASS' if evidence['passed'] else 'FAIL'}] evidence chain -> {out / 'evidence.md'}")

    emit({"evidence_json": str(out / "evidence.json"), "chain": chain, "passed": evidence["passed"]})
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
