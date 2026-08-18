#!/usr/bin/env python3
"""Prove the lab left nothing billable behind.

Terraform state is gone after `make destroy`, so this script does not trust it:
it sweeps SageMaker and S3 by the project prefix and asserts that no endpoint,
endpoint configuration, model or lab bucket survives.

A completed training job stays in SageMaker history forever. That is a record,
not a running resource, so it is reported and explicitly not counted as a
cleanup failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1 import aws_helpers as aws
from lab1.config import emit, evidence_dir, load_config, log


def bucket_exists(session, bucket: str) -> bool:
    try:
        aws.client(session, "s3").head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        if code == "403":
            # Someone else owns a bucket with this name; it is not ours and not
            # billable to this account, but say so rather than claiming success.
            log(f"[warn] head_bucket on {bucket} returned 403 - name exists outside this account")
            return False
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    args = parser.parse_args()

    cfg = load_config()
    prefix = cfg.bucket_prefix

    try:
        session = aws.make_session(cfg.region, args.profile)
        identity = aws.whoami(session)
        sagemaker = aws.client(session, "sagemaker")

        endpoints = sagemaker.list_endpoints(NameContains=prefix, MaxResults=100)["Endpoints"]
        configs = sagemaker.list_endpoint_configs(NameContains=prefix, MaxResults=100)[
            "EndpointConfigs"
        ]
        models = sagemaker.list_models(NameContains=prefix, MaxResults=100)["Models"]
        jobs = sagemaker.list_training_jobs(NameContains=prefix, MaxResults=100)[
            "TrainingJobSummaries"
        ]
        bucket = cfg.bucket_name(identity["account_id"])
        bucket_present = bucket_exists(session, bucket)
    except aws.AwsError as exc:
        log(f"[FAIL] {exc}")
        emit({"passed": False, "error": str(exc)})
        return 1

    checks = {
        "no_endpoint": {
            "passed": not endpoints,
            "detail": [e["EndpointName"] for e in endpoints] or f"no endpoint matching {prefix!r}",
        },
        "no_endpoint_configuration": {
            "passed": not configs,
            "detail": [c["EndpointConfigName"] for c in configs] or f"no endpoint config matching {prefix!r}",
        },
        "no_sagemaker_model": {
            "passed": not models,
            "detail": [m["ModelName"] for m in models] or f"no model matching {prefix!r}",
        },
        "no_lab_bucket": {
            "passed": not bucket_present,
            "detail": f"{bucket} still exists" if bucket_present else f"{bucket} is gone",
        },
    }

    result = {
        "region": cfg.region,
        "account_id": identity["account_id"],
        "name_prefix": prefix,
        "checks": checks,
        "training_jobs_in_history": [
            {"name": j["TrainingJobName"], "status": j["TrainingJobStatus"]} for j in jobs
        ],
        "training_history_is_not_billable": True,
        "passed": all(c["passed"] for c in checks.values()),
    }

    out = evidence_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "verify_clean.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    for name, check in checks.items():
        log(f"  [{'PASS' if check['passed'] else 'FAIL'}] {name}: {check['detail']}")
    if result["training_jobs_in_history"]:
        log(
            f"[info] {len(result['training_jobs_in_history'])} training job(s) remain in SageMaker "
            "history - a record, not a running resource, and not billable"
        )
    log(f"[{'PASS' if result['passed'] else 'FAIL'}] no billable serving resources remain")

    emit(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
