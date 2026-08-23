"""Thin Boto3 and Terraform glue shared by scripts/lab.py.

Two rules shape this module:

1. Nothing here ever prints or returns a credential. Identity is reported as
   account ID / ARN only.
2. Region is asserted, not assumed. The Academy lab only permits `us-east-1`.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError, TokenRetrievalError

from fiap_serving_scaling.config import TERRAFORM_DIR, log

BOTO_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

TERMINAL_TRAINING_STATUSES = {"Completed", "Failed", "Stopped"}
TERMINAL_ENDPOINT_STATUSES = {"InService", "Failed", "OutOfService"}
TERMINAL_TRANSFORM_STATUSES = {"Completed", "Failed", "Stopped"}


class AwsError(RuntimeError):
    """Actionable failure talking to AWS - message is meant for a student to read."""


def make_session(region: str, profile: str | None = None) -> boto3.session.Session:
    session = boto3.session.Session(profile_name=profile) if profile else boto3.session.Session()
    resolved = session.region_name
    if resolved and resolved != region:
        raise AwsError(
            f"session region is {resolved!r} but this lab requires {region!r}. "
            f"Export AWS_DEFAULT_REGION={region} or fix the profile."
        )
    if not resolved:
        session = boto3.session.Session(profile_name=profile, region_name=region)
    return session


def client(session: boto3.session.Session, service: str) -> Any:
    return session.client(service, config=BOTO_CONFIG)


def mask_arn(arn: str) -> str:
    parts = arn.split(":")
    if len(parts) > 4 and parts[4].isdigit() and len(parts[4]) == 12:
        parts[4] = f"{parts[4][:4]}{'*' * 4}{parts[4][-4:]}"
    return ":".join(parts)


def whoami(session: boto3.session.Session) -> dict[str, str]:
    try:
        identity = client(session, "sts").get_caller_identity()
    except (NoCredentialsError, TokenRetrievalError) as exc:
        raise AwsError(
            "no usable AWS credentials. Reopen the Academy Learner Lab and refresh "
            "the credentials configured for this environment."
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"ExpiredToken", "InvalidClientTokenId", "RequestExpired"}:
            raise AwsError(
                f"AWS credentials rejected ({code}). Academy session tokens expire; "
                "refresh them and try again."
            ) from exc
        raise
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "user_id_prefix": identity["UserId"].split(":")[0],
    }


def resolve_lab_role(session: boto3.session.Session, role_name: str) -> str:
    try:
        return client(session, "iam").get_role(RoleName=role_name)["Role"]["Arn"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "NoSuchEntity":
            raise AwsError(
                f"role {role_name!r} not found. This lab depends on the pre-provisioned "
                "Academy role and cannot create IAM roles itself."
            ) from exc
        if code == "AccessDenied":
            identity = whoami(session)
            arn = f"arn:aws:iam::{identity['account_id']}:role/{role_name}"
            log(f"[warn] iam:GetRole denied; assuming {arn} exists (Academy default)")
            return arn
        raise


# --------------------------------------------------------------------------- #
# Terraform outputs
# --------------------------------------------------------------------------- #


def terraform_outputs(directory: str | None = None) -> dict[str, Any]:
    cwd = directory or str(TERRAFORM_DIR)
    try:
        completed = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise AwsError("terraform binary not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise AwsError(f"terraform output failed in {cwd}: {exc.stderr.strip()}") from exc
    raw = json.loads(completed.stdout or "{}")
    return {key: value.get("value") for key, value in raw.items()}


def require_output(outputs: dict[str, Any], key: str) -> Any:
    if key not in outputs or outputs[key] in (None, ""):
        raise AwsError(
            f"terraform output {key!r} is not available. Run `make apply` first."
        )
    return outputs[key]


# --------------------------------------------------------------------------- #
# SageMaker: training / models / endpoints
# --------------------------------------------------------------------------- #


def describe_training_job(session: boto3.session.Session, job_name: str) -> dict[str, Any]:
    return client(session, "sagemaker").describe_training_job(TrainingJobName=job_name)


def wait_training_job(
    session: boto3.session.Session,
    job_name: str,
    poll_seconds: int = 20,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    sagemaker = client(session, "sagemaker")
    deadline = time.monotonic() + timeout_seconds
    last_secondary = ""
    while True:
        description = sagemaker.describe_training_job(TrainingJobName=job_name)
        status = description["TrainingJobStatus"]
        secondary = description.get("SecondaryStatus", "")
        if secondary != last_secondary:
            log(f"[training] {job_name}: {status} / {secondary}")
            last_secondary = secondary
        if status in TERMINAL_TRAINING_STATUSES:
            return description
        if time.monotonic() > deadline:
            raise AwsError(
                f"training job {job_name} still {status}/{secondary} after "
                f"{timeout_seconds}s"
            )
        time.sleep(poll_seconds)


def describe_endpoint(session: boto3.session.Session, endpoint_name: str) -> dict[str, Any]:
    return client(session, "sagemaker").describe_endpoint(EndpointName=endpoint_name)


def describe_endpoint_config(session: boto3.session.Session, name: str) -> dict[str, Any]:
    return client(session, "sagemaker").describe_endpoint_config(EndpointConfigName=name)


def wait_endpoint_in_service(
    session: boto3.session.Session,
    endpoint_name: str,
    poll_seconds: int = 15,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    sagemaker = client(session, "sagemaker")
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while True:
        description = sagemaker.describe_endpoint(EndpointName=endpoint_name)
        status = description["EndpointStatus"]
        if status != last_status:
            log(f"[endpoint] {endpoint_name}: {status}")
            last_status = status
        if status in TERMINAL_ENDPOINT_STATUSES:
            return description
        if time.monotonic() > deadline:
            raise AwsError(f"endpoint {endpoint_name} still {status} after {timeout_seconds}s")
        time.sleep(poll_seconds)


def object_exists(session: boto3.session.Session, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        head = client(session, "s3").head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    return {"content_length": int(head["ContentLength"]), "etag": head["ETag"].strip('"')}


def split_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise AwsError(f"not an S3 URI: {uri!r}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    if not bucket or not key:
        raise AwsError(f"S3 URI missing bucket or key: {uri!r}")
    return bucket, key


def invoke_endpoint_csv(
    session: boto3.session.Session, endpoint_name: str, body: str
) -> tuple[list[float], float]:
    """Send headerless CSV, return (probabilities, wall_clock_seconds)."""
    runtime = client(session, "sagemaker-runtime")
    started = time.monotonic()
    try:
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="text/csv",
            Accept="text/csv",
            Body=body.encode("utf-8"),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        raise AwsError(
            f"invoke_endpoint failed on {endpoint_name!r} ({code}): "
            f"{exc.response.get('Error', {}).get('Message', '')}"
        ) from exc
    elapsed = time.monotonic() - started
    payload = response["Body"].read().decode("utf-8").strip()
    return parse_csv_probabilities(payload, expected=len(body.strip().split("\n"))), elapsed


def invoke_endpoint_async(
    session: boto3.session.Session,
    endpoint_name: str,
    input_s3_uri: str,
) -> dict[str, Any]:
    runtime = client(session, "sagemaker-runtime")
    try:
        response = runtime.invoke_endpoint_async(
            EndpointName=endpoint_name,
            InputLocation=input_s3_uri,
            ContentType="text/csv",
            Accept="text/csv",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        raise AwsError(f"invoke_endpoint_async failed ({code}): {exc}") from exc
    return {
        "inference_id": response["InferenceId"],
        "output_location": response["OutputLocation"],
        "failure_location": response.get("FailureLocation"),
    }


def parse_csv_probabilities(payload: str, expected: int | None = None) -> list[float]:
    tokens: list[str] = []
    for line in payload.replace("\r", "").split("\n"):
        tokens.extend(token for token in line.split(",") if token.strip())
    values: list[float] = []
    for token in tokens:
        value = float(token)
        if not (0.0 <= value <= 1.0):
            raise AwsError(f"probability out of [0,1]: {value}")
        values.append(value)
    if expected is not None and len(values) != expected:
        raise AwsError(f"endpoint returned {len(values)} probabilities for {expected} rows")
    return values


# --------------------------------------------------------------------------- #
# Batch Transform
# --------------------------------------------------------------------------- #


def create_transform_job(
    session: boto3.session.Session,
    job_name: str,
    model_name: str,
    input_s3_uri: str,
    output_s3_uri: str,
    instance_type: str,
    max_concurrent_transforms: int,
    max_payload_in_mb: int,
    batch_strategy: str,
) -> None:
    sagemaker = client(session, "sagemaker")
    sagemaker.create_transform_job(
        TransformJobName=job_name,
        ModelName=model_name,
        MaxConcurrentTransforms=max_concurrent_transforms,
        MaxPayloadInMB=max_payload_in_mb,
        BatchStrategy=batch_strategy,
        TransformInput={
            "DataSource": {
                "S3DataSource": {"S3DataType": "S3Prefix", "S3Uri": input_s3_uri}
            },
            "ContentType": "text/csv",
            "SplitType": "Line",
        },
        TransformOutput={
            "S3OutputPath": output_s3_uri,
            "Accept": "text/csv",
            "AssembleWith": "Line",
        },
        TransformResources={
            "InstanceType": instance_type,
            "InstanceCount": 1,
        },
    )


def wait_transform_job(
    session: boto3.session.Session,
    job_name: str,
    poll_seconds: int = 20,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    sagemaker = client(session, "sagemaker")
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while True:
        description = sagemaker.describe_transform_job(TransformJobName=job_name)
        status = description["TransformJobStatus"]
        if status != last_status:
            log(f"[batch] {job_name}: {status}")
            last_status = status
        if status in TERMINAL_TRANSFORM_STATUSES:
            return description
        if time.monotonic() > deadline:
            raise AwsError(f"transform job {job_name} still {status} after {timeout_seconds}s")
        time.sleep(poll_seconds)


# --------------------------------------------------------------------------- #
# Application Auto Scaling
# --------------------------------------------------------------------------- #


def describe_scalable_targets(
    session: boto3.session.Session, resource_id: str, scalable_dimension: str = "sagemaker:variant:DesiredInstanceCount"
) -> list[dict[str, Any]]:
    aas = client(session, "application-autoscaling")
    response = aas.describe_scalable_targets(
        ServiceNamespace="sagemaker",
        ResourceIds=[resource_id],
        ScalableDimension=scalable_dimension,
    )
    return response["ScalableTargets"]


def describe_scaling_policies(session: boto3.session.Session, resource_id: str) -> list[dict[str, Any]]:
    aas = client(session, "application-autoscaling")
    response = aas.describe_scaling_policies(
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
    )
    return response["ScalingPolicies"]


def register_scalable_target_min_capacity(
    session: boto3.session.Session,
    resource_id: str,
    min_capacity: int,
    max_capacity: int,
    scalable_dimension: str = "sagemaker:variant:DesiredInstanceCount",
) -> None:
    """Used only by `make scale-demo` to move the floor temporarily and back."""
    aas = client(session, "application-autoscaling")
    aas.register_scalable_target(
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension=scalable_dimension,
        MinCapacity=min_capacity,
        MaxCapacity=max_capacity,
    )


def set_endpoint_desired_capacity(
    session: boto3.session.Session,
    endpoint_name: str,
    desired_instance_count: int,
    variant_name: str = "AllTraffic",
) -> None:
    """Force DesiredInstanceCount directly. Registering a lower MaxCapacity with
    Application Auto Scaling does not by itself scale a variant in: scale-in only
    happens when the target-tracking alarm evaluates enough datapoints, which can
    take longer than a classroom demo's timeout. Scaling out (raising MinCapacity
    above current capacity) does not have this problem, so only the restore side
    needs this direct call."""
    sagemaker = client(session, "sagemaker")
    sagemaker.update_endpoint_weights_and_capacities(
        EndpointName=endpoint_name,
        DesiredWeightsAndCapacities=[
            {"VariantName": variant_name, "DesiredInstanceCount": desired_instance_count}
        ],
    )


def wait_instance_count(
    session: boto3.session.Session,
    endpoint_name: str,
    target_count: int,
    poll_seconds: int = 15,
    timeout_seconds: int = 600,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    last_count = -1
    while True:
        description = describe_endpoint(session, endpoint_name)
        variants = description.get("ProductionVariants", [])
        current = variants[0]["CurrentInstanceCount"] if variants else 0
        if current != last_count:
            log(f"[scale] {endpoint_name}: CurrentInstanceCount={current} (target {target_count})")
            last_count = current
        if current == target_count:
            return current
        if time.monotonic() > deadline:
            raise AwsError(
                f"endpoint {endpoint_name} did not reach {target_count} instances "
                f"within {timeout_seconds}s (last seen {current})"
            )
        time.sleep(poll_seconds)


# --------------------------------------------------------------------------- #
# S3 convenience
# --------------------------------------------------------------------------- #


def upload_file(session: boto3.session.Session, path: str, bucket: str, key: str) -> str:
    client(session, "s3").upload_file(path, bucket, key)
    return f"s3://{bucket}/{key}"


def download_text(session: boto3.session.Session, bucket: str, key: str) -> str:
    body = client(session, "s3").get_object(Bucket=bucket, Key=key)["Body"]
    return body.read().decode("utf-8")


def list_objects(session: boto3.session.Session, bucket: str, prefix: str) -> list[str]:
    paginator = client(session, "s3").get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys


def poll_for_object(
    session: boto3.session.Session,
    bucket: str,
    key: str,
    poll_seconds: int = 10,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        head = object_exists(session, bucket, key)
        if head is not None:
            return head
        if time.monotonic() > deadline:
            raise AwsError(f"s3://{bucket}/{key} did not appear within {timeout_seconds}s")
        time.sleep(poll_seconds)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
