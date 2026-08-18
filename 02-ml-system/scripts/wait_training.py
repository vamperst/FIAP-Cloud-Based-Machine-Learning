#!/usr/bin/env python3
"""Bridge between the training stage and the serving stage.

Provider 6.60.0's `aws_sagemaker_training_job` returns as soon as the job is
InProgress and exports no artifact URI, so a green `terraform apply` says nothing
about whether a model exists. This script closes that gap:

1. waits for a terminal training status and surfaces `FailureReason` verbatim;
2. reads the artifact URI from `DescribeTrainingJob` - the authoritative value,
   never a path assembled from a naming convention;
3. proves the object exists and is non-empty with `HeadObject`;
4. writes `terraform/artifact.auto.tfvars.json` so stage two of `make apply`
   needs no copy/paste.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1 import aws_helpers as aws
from lab1.config import TERRAFORM_DIR, emit, evidence_dir, load_config, log

HANDOFF_FILE = "artifact.auto.tfvars.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--job-name", help="defaults to the training_job_name Terraform output")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--poll", type=int, default=20)
    args = parser.parse_args()

    cfg = load_config()
    try:
        session = aws.make_session(cfg.region, args.profile)
        job_name = args.job_name or aws.require_output(aws.terraform_outputs(), "training_job_name")

        log(f"[wait] waiting for training job {job_name}")
        description = aws.wait_training_job(
            session, job_name, poll_seconds=args.poll, timeout_seconds=args.timeout
        )
        status = description["TrainingJobStatus"]
        if status != "Completed":
            reason = description.get("FailureReason", "(no FailureReason reported)")
            log(f"[FAIL] training job {job_name} ended as {status}: {reason}")
            log("[hint] full logs: CloudWatch group /aws/sagemaker/TrainingJobs")
            emit({"passed": False, "training_job_name": job_name, "status": status, "failure_reason": reason})
            return 1

        artifact_uri = description.get("ModelArtifacts", {}).get("S3ModelArtifacts", "")
        if not artifact_uri:
            raise aws.AwsError(
                f"training job {job_name} completed but reported no ModelArtifacts.S3ModelArtifacts"
            )

        bucket, key = aws.split_s3_uri(artifact_uri)
        head = aws.object_exists(session, bucket, key)
        if head is None:
            raise aws.AwsError(f"artifact {artifact_uri} is not in S3 - refusing to deploy a model")
        if head["content_length"] <= 0:
            raise aws.AwsError(f"artifact {artifact_uri} is empty - refusing to deploy a model")
    except aws.AwsError as exc:
        log(f"[FAIL] {exc}")
        emit({"passed": False, "error": str(exc)})
        return 1

    handoff = TERRAFORM_DIR / HANDOFF_FILE
    # `deploy_serving` is persisted here, not passed as `-var`, so that a later
    # `terraform plan` or `destroy` sees the same stage the state represents.
    handoff.write_text(
        json.dumps({"deploy_serving": True, "model_artifact_uri": artifact_uri}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Kept for the evidence package: these fields are the proof that training
    # really ran with the configuration the repository claims.
    record = {
        "passed": True,
        "training_job_name": job_name,
        "status": status,
        "secondary_status": description.get("SecondaryStatus"),
        "creation_time": aws.json_safe(description.get("CreationTime")),
        "training_start_time": aws.json_safe(description.get("TrainingStartTime")),
        "training_end_time": aws.json_safe(description.get("TrainingEndTime")),
        "billable_seconds": description.get("BillableTimeInSeconds"),
        "training_image": description.get("AlgorithmSpecification", {}).get("TrainingImage"),
        "training_input_mode": description.get("AlgorithmSpecification", {}).get("TrainingInputMode"),
        "hyperparameters": description.get("HyperParameters", {}),
        "input_channels": [
            {
                "channel": channel.get("ChannelName"),
                "s3_uri": channel.get("DataSource", {}).get("S3DataSource", {}).get("S3Uri"),
                "content_type": channel.get("ContentType"),
            }
            for channel in description.get("InputDataConfig", [])
        ],
        "output_s3_path": description.get("OutputDataConfig", {}).get("S3OutputPath"),
        "instance_type": description.get("ResourceConfig", {}).get("InstanceType"),
        "instance_count": description.get("ResourceConfig", {}).get("InstanceCount"),
        "volume_size_in_gb": description.get("ResourceConfig", {}).get("VolumeSizeInGB"),
        "max_runtime_in_seconds": description.get("StoppingCondition", {}).get("MaxRuntimeInSeconds"),
        "final_metrics": [
            {"name": m.get("MetricName"), "value": m.get("Value")}
            for m in description.get("FinalMetricDataList", [])
        ],
        "model_artifact_uri": artifact_uri,
        "model_artifact_bytes": head["content_length"],
        "model_artifact_etag": head["etag"],
        "handoff_file": str(handoff),
    }

    out = evidence_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "training_job.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    log(f"[wait] {status} in {record['billable_seconds']}s billable")
    for metric in record["final_metrics"]:
        log(f"[wait] final metric {metric['name']}={metric['value']}")
    log(f"[wait] artifact {artifact_uri} ({head['content_length']} bytes, verified with HeadObject)")
    log(f"[wait] wrote {handoff.name} for the serving stage")

    emit(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
