"""Thin Boto3 and Terraform glue shared by the control scripts.

Two rules shape this module:

1. Nothing here ever prints or returns a credential. Identity is reported as
   account ID / ARN only, which is what evidence needs and what a screenshot can
   safely show.
2. Region is asserted, not assumed. The Academy lab only permits `us-east-1`,
   and a silently wrong region produces confusing "resource not found" errors
   much later, so every session is validated at construction time.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError, TokenRetrievalError

from lab1.config import TERRAFORM_DIR, log

# Retries matter here: Academy accounts are shared and throttling is common.
BOTO_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"})

TERMINAL_TRAINING_STATUSES = {"Completed", "Failed", "Stopped"}
TERMINAL_ENDPOINT_STATUSES = {"InService", "Failed", "OutOfService"}


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
        # A profile without a region is common in Academy; pin it explicitly
        # instead of letting each client guess.
        session = boto3.session.Session(profile_name=profile, region_name=region)
    return session


def client(session: boto3.session.Session, service: str) -> Any:
    return session.client(service, config=BOTO_CONFIG)


def whoami(session: boto3.session.Session) -> dict[str, str]:
    """Caller identity without secrets. Fails with a readable message when expired."""
    try:
        identity = client(session, "sts").get_caller_identity()
    except (NoCredentialsError, TokenRetrievalError) as exc:
        raise AwsError(
            "no usable AWS credentials. In AWS Academy, reopen the lab and copy the "
            "fresh credentials into your environment or profile."
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"ExpiredToken", "InvalidClientTokenId", "RequestExpired"}:
            raise AwsError(
                f"AWS credentials rejected ({code}). Academy session tokens expire; "
                "start the lab again and refresh them."
            ) from exc
        raise
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "user_id_prefix": identity["UserId"].split(":")[0],
    }


def resolve_lab_role(session: boto3.session.Session, role_name: str) -> str:
    """Return the LabRole ARN. Academy forbids creating roles, so it must exist."""
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
            # Some Academy policies deny iam:GetRole while still allowing PassRole.
            identity = whoami(session)
            arn = f"arn:aws:iam::{identity['account_id']}:role/{role_name}"
            log(f"[warn] iam:GetRole denied; assuming {arn} exists (Academy default)")
            return arn
        raise


# --------------------------------------------------------------------------- #
# Terraform outputs
# --------------------------------------------------------------------------- #


def terraform_outputs(directory: str | None = None) -> dict[str, Any]:
    """Read `terraform output -json` and flatten to plain values."""
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
            f"terraform output {key!r} is not available. Run `make apply` first "
            "(the serving stage only exists after deployment)."
        )
    return outputs[key]


# --------------------------------------------------------------------------- #
# SageMaker
# --------------------------------------------------------------------------- #


def describe_training_job(session: boto3.session.Session, job_name: str) -> dict[str, Any]:
    return client(session, "sagemaker").describe_training_job(TrainingJobName=job_name)


def wait_training_job(
    session: boto3.session.Session,
    job_name: str,
    poll_seconds: int = 20,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Poll until the job reaches a terminal state, narrating progress to stderr."""
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
                f"{timeout_seconds}s; check the SageMaker console or CloudWatch logs"
            )
        time.sleep(poll_seconds)


def describe_endpoint(session: boto3.session.Session, endpoint_name: str) -> dict[str, Any]:
    return client(session, "sagemaker").describe_endpoint(EndpointName=endpoint_name)


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
) -> list[float]:
    """Send headerless CSV and parse one probability per input row."""
    runtime = client(session, "sagemaker-runtime")
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
    payload = response["Body"].read().decode("utf-8").strip()
    return parse_csv_probabilities(payload, expected=len(body.split("\n")))


def parse_csv_probabilities(payload: str, expected: int | None = None) -> list[float]:
    """Built-in XGBoost answers with newline- or comma-separated probabilities."""
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


def batched(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def json_safe(value: Any) -> Any:
    """Make a Boto3 response JSON-serialisable (its timestamps are datetimes)."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
