"""The data contract must pass on a freshly generated dataset - and only then."""

from __future__ import annotations

from lab1.config import MODEL_TEST_FEATURES_FILE, MODEL_TRAIN_FILE, SOURCE_FILE
from lab1.data_contract import validate


def test_fresh_dataset_satisfies_every_check(cfg, schema, data_dir):
    report = validate(cfg, schema, data_dir)
    assert report.checks, "a report with no checks would silently pass everything"
    assert report.ok, [c.as_dict() for c in report.failed]


def test_source_has_a_header_and_model_files_do_not(cfg, data_dir):
    source_first_line = (data_dir / SOURCE_FILE).read_text(encoding="utf-8").split("\n")[0]
    train_first_line = (data_dir / MODEL_TRAIN_FILE).read_text(encoding="utf-8").split("\n")[0]

    assert source_first_line.startswith(cfg.id_column)
    assert cfg.label in source_first_line
    assert all(cell.replace(".", "").replace("-", "").isdigit() for cell in train_first_line.split(","))


def test_training_file_has_label_first_and_one_more_column_than_features(cfg, data_dir):
    rows = [r for r in (data_dir / MODEL_TRAIN_FILE).read_text(encoding="utf-8").split("\n") if r]
    widths = {len(r.split(",")) for r in rows}
    assert widths == {len(cfg.feature_order) + 1}
    assert {r.split(",")[0] for r in rows} <= {"0", "1"}


def test_inference_file_has_no_label(cfg, data_dir):
    rows = [
        r for r in (data_dir / MODEL_TEST_FEATURES_FILE).read_text(encoding="utf-8").split("\n") if r
    ]
    assert {len(r.split(",")) for r in rows} == {len(cfg.feature_order)}


def test_prevalence_is_inside_the_documented_range(cfg, data_dir):
    rows = [r for r in (data_dir / SOURCE_FILE).read_text(encoding="utf-8").split("\n")[1:] if r]
    positives = sum(1 for r in rows if r.split(",")[-1] == "1")
    low, high = cfg.prevalence_range
    assert low <= positives / len(rows) <= high


def test_every_split_clears_the_minimum_row_count(cfg, schema, data_dir):
    report = validate(cfg, schema, data_dir)
    minimum_checks = [c for c in report.checks if c.name.endswith(".min_rows")]
    assert len(minimum_checks) == 3
    assert all(c.passed for c in minimum_checks)
