#!/usr/bin/env python3
"""Generate the deterministic synthetic dataset.

Same seed, same bytes: the manifest records a SHA-256 per file so a second run -
on another machine, in Codespaces, next semester - can be proven identical
instead of assumed identical.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab1.config import DATA_DIR, emit, load_config, log
from lab1.dataset import write_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DATA_DIR, help="output directory")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the output directory first, to prove generation from scratch",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.clean and args.out.exists():
        log(f"[data] removing {args.out}")
        shutil.rmtree(args.out)

    manifest = write_dataset(cfg, args.out)

    log(f"[data] seed {manifest['seed']} schema {manifest['schema_version']}")
    log(f"[data] source {manifest['source']['rows']} rows, prevalence {manifest['source']['prevalence']}")
    for name, split in manifest["splits"].items():
        log(f"[data] {name:<10} {split['rows']:>5} rows  prevalence {split['prevalence']}  {split['sha256'][:12]}")
    log(f"[data] written to {args.out}")

    emit(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
