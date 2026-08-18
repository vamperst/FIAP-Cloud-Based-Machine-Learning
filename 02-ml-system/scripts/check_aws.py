#!/usr/bin/env python3
"""Preflight: is this environment allowed to build the lab at all?

Checks identity, region and the pre-provisioned execution role before any
resource is created, because every later failure mode (wrong region, expired
Academy token, missing LabRole) is far cheaper to diagnose here.

Prints a human report to stderr and the machine-readable result to stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Works whether the script is called directly or through the Makefile.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1 import aws_helpers as aws
from lab1.config import emit, load_config, log


def mask_arn(arn: str) -> str:
    """Keep the shape of the ARN visible while hiding the account digits."""
    parts = arn.split(":")
    if len(parts) > 4 and parts[4].isdigit() and len(parts[4]) == 12:
        parts[4] = f"{parts[4][:4]}{'*' * 4}{parts[4][-4:]}"
    return ":".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    parser.add_argument("--json", action="store_true", help="only the JSON result on stdout")
    args = parser.parse_args()

    cfg = load_config()
    result: dict[str, object] = {"region_required": cfg.region, "checks": {}}

    try:
        session = aws.make_session(cfg.region, args.profile)
        identity = aws.whoami(session)
        role_arn = aws.resolve_lab_role(session, cfg.execution_role_name)
    except aws.AwsError as exc:
        log(f"[FAIL] {exc}")
        result["passed"] = False
        result["error"] = str(exc)
        emit(result)
        return 1

    result["checks"] = {
        "credentials_usable": True,
        "region_is_required_region": session.region_name == cfg.region,
        "execution_role_resolved": bool(role_arn),
    }
    result["account_id"] = identity["account_id"]
    result["caller_arn"] = identity["arn"]
    result["execution_role_arn"] = role_arn
    result["bucket_name"] = cfg.bucket_name(identity["account_id"])
    result["passed"] = all(result["checks"].values())

    if not args.json:
        log("AWS preflight")
        log(f"  account          : {identity['account_id']}")
        log(f"  caller           : {mask_arn(identity['arn'])}")
        log(f"  region           : {session.region_name} (required {cfg.region})")
        log(f"  execution role   : {mask_arn(role_arn)}")
        log(f"  lab bucket to use: {result['bucket_name']}")
        log("  credentials are never printed by this lab")
        log(f"[{'PASS' if result['passed'] else 'FAIL'}] preflight")

    emit(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
