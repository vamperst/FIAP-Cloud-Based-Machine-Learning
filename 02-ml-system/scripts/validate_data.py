#!/usr/bin/env python3
"""Run the data contract. Non-zero exit on any violation.

This runs before anything touches AWS: a dataset that fails here never becomes a
training job, so no student pays for compute on data nobody checked.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1.config import DATA_DIR, emit, load_config, load_schema, log
from lab1.data_contract import validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    cfg, schema = load_config(), load_schema()
    report = validate(cfg, schema, args.data)

    log(f"data contract: {len(report.checks)} checks against {args.data}")
    for check in report.checks:
        log(f"  [{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
    log(f"[{'PASS' if report.ok else 'FAIL'}] {len(report.failed)} of {len(report.checks)} checks failed")

    emit(report.as_dict())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
