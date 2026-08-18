"""Determinism: same seed, same bytes.

If this file fails, everything downstream loses its meaning - the fingerprints in
the evidence package would no longer identify a dataset.
"""

from __future__ import annotations

import json

from lab1.config import (
    MANIFEST_FILE,
    MODEL_TEST_FEATURES_FILE,
    MODEL_TRAIN_FILE,
    MODEL_VALIDATION_FILE,
    SOURCE_FILE,
    TEST_LABELS_FILE,
)
from lab1.dataset import generate_source, sha256_file, stratified_split, write_dataset

GENERATED_FILES = (
    SOURCE_FILE,
    MODEL_TRAIN_FILE,
    MODEL_VALIDATION_FILE,
    MODEL_TEST_FEATURES_FILE,
    TEST_LABELS_FILE,
    MANIFEST_FILE,
)


def test_two_runs_produce_identical_bytes(cfg, tmp_path):
    first = write_dataset(cfg, tmp_path / "run1")
    second = write_dataset(cfg, tmp_path / "run2")

    assert first == second, "the manifest itself must be reproducible, timestamps included"
    for name in GENERATED_FILES:
        assert sha256_file(tmp_path / "run1" / name) == sha256_file(tmp_path / "run2" / name), name


def test_generator_is_pure_function_of_the_seed(cfg):
    a = generate_source(cfg)
    b = generate_source(cfg)
    for column, values in a.items():
        assert (values == b[column]).all(), column


def test_changing_the_seed_changes_the_data(cfg, tmp_path):
    from dataclasses import replace

    other_raw = json.loads(json.dumps(cfg.raw))
    other_raw["dataset"]["seed"] = cfg.seed + 1
    other = replace(cfg, raw=other_raw)

    baseline = write_dataset(cfg, tmp_path / "baseline")
    shifted = write_dataset(other, tmp_path / "shifted")

    assert baseline["source"]["sha256"] != shifted["source"]["sha256"]


def test_manifest_records_a_fingerprint_for_every_generated_file(cfg, data_dir):
    manifest = json.loads((data_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert len(manifest["source"]["sha256"]) == 64
    for split in ("train", "validation", "test"):
        assert len(manifest["splits"][split]["sha256"]) == 64
    assert manifest["splits"]["test"]["labels_sha256"]
    assert manifest["generator"]["coefficients"], "the DGP must be part of the record"


def test_split_sizes_follow_the_configured_fractions(cfg):
    splits = stratified_split(cfg, generate_source(cfg))
    assert splits["train"].rows == 2800
    assert splits["validation"].rows == 600
    assert splits["test"].rows == 600
    assert sum(s.rows for s in splits.values()) == cfg.rows


def test_stratification_keeps_prevalence_stable(cfg):
    source = generate_source(cfg)
    splits = stratified_split(cfg, source)
    overall = float(source[cfg.label].mean())
    for split in splits.values():
        # Stratified means "same class balance", within one row of rounding.
        assert abs(split.prevalence - overall) < 0.01, split.name
