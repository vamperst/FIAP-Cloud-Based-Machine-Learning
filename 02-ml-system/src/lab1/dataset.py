"""Deterministic synthetic dataset for Lab 1.

Why synthetic: the lesson needs every Academy account to run the *same logical
experiment*. A downloaded dataset can change or disappear independently of this
repository; a seeded generator cannot. See docs/adr/0002-synthetic-dataset.md.

Determinism contract
--------------------
Two properties are guaranteed, in this order:

1. Same seed + same numpy version -> identical bytes in every generated file.
2. Cross-platform stability (arm64 vs x86_64): every feature is rounded to a
   fixed number of decimals *before* the label is computed and before it is
   written. Transcendental functions (exp/log inside normal/gamma/poisson) can
   differ by one ULP between SIMD implementations; rounding to 2 decimals
   absorbs that, so the CSV bytes stay identical. The label draw uses
   `rng.random() < p` instead of `rng.binomial`, because `random()` is pure bit
   manipulation and therefore exact everywhere.

The draw order below is part of the contract: reordering it changes the RNG
stream and therefore every file hash.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from lab1.config import (
    MANIFEST_FILE,
    MODEL_TEST_FEATURES_FILE,
    MODEL_TRAIN_FILE,
    MODEL_VALIDATION_FILE,
    SOURCE_FILE,
    TEST_LABELS_FILE,
    LabConfig,
    log,
)

# Coefficients of the data-generating process. They are a transparent logistic
# model: a reader can predict the direction of every feature's effect without
# training anything, which is the point in the first class.
DGP = {
    "intercept": -0.45,
    "tenure_months": -0.045,
    "support_calls_90d": 0.65,
    "payment_delay_days": 0.065,
    "monthly_charges": 0.012,
    "monthly_charges_center": 100.0,
    "annual_contract": -0.95,
    "premium_plan": -0.40,
    "usage_score": -0.018,
    "usage_score_center": 60.0,
}

DECIMALS = {
    "tenure_months": 0,
    "monthly_charges": 2,
    "support_calls_90d": 0,
    "payment_delay_days": 2,
    "usage_score": 2,
    "annual_contract": 0,
    "premium_plan": 0,
    "churn": 0,
}


@dataclass(frozen=True)
class Split:
    name: str
    ids: np.ndarray
    features: dict[str, np.ndarray]
    labels: np.ndarray

    @property
    def rows(self) -> int:
        return int(self.ids.shape[0])

    @property
    def prevalence(self) -> float:
        return float(self.labels.mean())


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def generate_source(cfg: LabConfig) -> dict[str, np.ndarray]:
    """Generate the analysis representation, including `observation_id`."""
    rng = np.random.default_rng(cfg.seed)
    n = cfg.rows

    observation_id = np.arange(1, n + 1, dtype=np.int64)

    # Draw order is part of the determinism contract - do not reorder.
    tenure_months = rng.integers(1, 73, size=n).astype(np.int64)
    monthly_charges = np.round(np.clip(rng.normal(110.0, 45.0, size=n), 20.0, 260.0), 2)
    support_calls_90d = np.clip(rng.poisson(1.5, size=n), 0, 30).astype(np.int64)
    payment_delay_days = np.round(np.clip(rng.gamma(2.0, 5.0, size=n), 0.0, 45.0), 2)
    usage_score = np.round(np.clip(rng.normal(65.0, 20.0, size=n), 5.0, 100.0), 2)
    annual_contract = (rng.random(size=n) < 0.45).astype(np.int64)
    premium_plan = (rng.random(size=n) < 0.35).astype(np.int64)

    logit = (
        DGP["intercept"]
        + DGP["tenure_months"] * tenure_months
        + DGP["support_calls_90d"] * support_calls_90d
        + DGP["payment_delay_days"] * payment_delay_days
        + DGP["monthly_charges"] * (monthly_charges - DGP["monthly_charges_center"])
        + DGP["annual_contract"] * annual_contract
        + DGP["premium_plan"] * premium_plan
        + DGP["usage_score"] * (usage_score - DGP["usage_score_center"])
    )
    churn = (rng.random(size=n) < _sigmoid(logit)).astype(np.int64)

    return {
        "observation_id": observation_id,
        "tenure_months": tenure_months,
        "monthly_charges": monthly_charges,
        "support_calls_90d": support_calls_90d,
        "payment_delay_days": payment_delay_days,
        "usage_score": usage_score,
        "annual_contract": annual_contract,
        "premium_plan": premium_plan,
        "churn": churn,
    }


def stratified_split(cfg: LabConfig, source: dict[str, np.ndarray]) -> dict[str, Split]:
    """Deterministic stratified split, disjoint by construction.

    Each class is permuted independently with its own seeded generator, then cut
    at the configured fractions. Rows are finally ordered by `observation_id` so
    the file layout does not depend on concatenation order.
    """
    labels = source["churn"]
    fractions = cfg.split_fractions
    train_cut, validation_cut = fractions["train"], fractions["train"] + fractions["validation"]

    # Offset seed so the split stream can never coincide with the generator stream.
    rng = np.random.default_rng(cfg.seed + 1)

    buckets: dict[str, list[np.ndarray]] = {"train": [], "validation": [], "test": []}
    for class_value in (0, 1):
        class_positions = np.flatnonzero(labels == class_value)
        shuffled = rng.permutation(class_positions)
        n_class = shuffled.shape[0]
        i_train = int(round(n_class * train_cut))
        i_validation = int(round(n_class * validation_cut))
        buckets["train"].append(shuffled[:i_train])
        buckets["validation"].append(shuffled[i_train:i_validation])
        buckets["test"].append(shuffled[i_validation:])

    splits: dict[str, Split] = {}
    for name, parts in buckets.items():
        positions = np.sort(np.concatenate(parts))
        splits[name] = Split(
            name=name,
            ids=source["observation_id"][positions],
            features={f: source[f][positions] for f in cfg.feature_order},
            labels=labels[positions],
        )
    return splits


def _format(column: str, value: Any) -> str:
    decimals = DECIMALS[column]
    if decimals == 0:
        return str(int(value))
    return f"{float(value):.{decimals}f}"


def _write_csv(path: Path, header: Sequence[str] | None, rows: Iterable[Sequence[str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if header is not None:
            writer.writerow(header)
        writer.writerows(rows)
    return sha256_file(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def serialize_training_rows(cfg: LabConfig, split: Split) -> list[list[str]]:
    """Headerless, label first - the built-in XGBoost training contract."""
    columns = [cfg.label, *cfg.feature_order]
    values = {cfg.label: split.labels, **split.features}
    return [[_format(c, values[c][i]) for c in columns] for i in range(split.rows)]


def serialize_feature_rows(cfg: LabConfig, split: Split) -> list[list[str]]:
    """Headerless, no label - the inference contract."""
    return [
        [_format(c, split.features[c][i]) for c in cfg.feature_order]
        for i in range(split.rows)
    ]


def write_dataset(cfg: LabConfig, out_dir: Path) -> dict[str, Any]:
    """Write source + model-ready files and return the deterministic manifest."""
    source = generate_source(cfg)
    splits = stratified_split(cfg, source)

    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"[data] seed={cfg.seed} rows={cfg.rows} out={out_dir}")

    source_columns = [cfg.id_column, *cfg.feature_order, cfg.label]
    source_rows = [
        [str(int(source[cfg.id_column][i]))]
        + [_format(c, source[c][i]) for c in cfg.feature_order]
        + [_format(cfg.label, source[cfg.label][i])]
        for i in range(cfg.rows)
    ]
    source_sha = _write_csv(out_dir / SOURCE_FILE, source_columns, source_rows)

    train_sha = _write_csv(
        out_dir / MODEL_TRAIN_FILE, None, serialize_training_rows(cfg, splits["train"])
    )
    validation_sha = _write_csv(
        out_dir / MODEL_VALIDATION_FILE, None, serialize_training_rows(cfg, splits["validation"])
    )
    test_features_sha = _write_csv(
        out_dir / MODEL_TEST_FEATURES_FILE, None, serialize_feature_rows(cfg, splits["test"])
    )
    test_labels_sha = _write_csv(
        out_dir / TEST_LABELS_FILE,
        [cfg.id_column, cfg.label],
        [
            [str(int(splits["test"].ids[i])), _format(cfg.label, splits["test"].labels[i])]
            for i in range(splits["test"].rows)
        ],
    )

    manifest: dict[str, Any] = {
        "schema_version": cfg.schema_version,
        "seed": cfg.seed,
        "rows": cfg.rows,
        "label": cfg.label,
        "id_column": cfg.id_column,
        "feature_order": cfg.feature_order,
        "generator": {
            "kind": "logistic-dgp",
            "numpy_version": np.__version__,
            "coefficients": DGP,
            "decimals": DECIMALS,
        },
        "source": {
            "file": SOURCE_FILE,
            "rows": cfg.rows,
            "sha256": source_sha,
            "prevalence": round(float(source[cfg.label].mean()), 6),
        },
        "splits": {
            "train": {
                "file": MODEL_TRAIN_FILE,
                "rows": splits["train"].rows,
                "sha256": train_sha,
                "prevalence": round(splits["train"].prevalence, 6),
                "header": False,
                "label_position": "first",
            },
            "validation": {
                "file": MODEL_VALIDATION_FILE,
                "rows": splits["validation"].rows,
                "sha256": validation_sha,
                "prevalence": round(splits["validation"].prevalence, 6),
                "header": False,
                "label_position": "first",
            },
            "test": {
                "file": MODEL_TEST_FEATURES_FILE,
                "rows": splits["test"].rows,
                "sha256": test_features_sha,
                "labels_file": TEST_LABELS_FILE,
                "labels_sha256": test_labels_sha,
                "prevalence": round(splits["test"].prevalence, 6),
                "header": False,
                "label_present_in_features": False,
            },
        },
    }

    manifest_path = out_dir / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest["manifest_sha256"] = sha256_file(manifest_path)

    return manifest


def read_manifest(out_dir: Path) -> dict[str, Any]:
    with (out_dir / MANIFEST_FILE).open(encoding="utf-8") as handle:
        return json.load(handle)
