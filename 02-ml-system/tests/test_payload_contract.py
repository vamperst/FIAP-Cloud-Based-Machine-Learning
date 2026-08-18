"""Payload contract.

The endpoint accepts positional CSV: a reordered feature vector is still a valid
request and still returns a confident, wrong answer. These tests are the only
thing standing between that bug and the classroom.
"""

from __future__ import annotations

import csv

import pytest

from lab1.config import MODEL_TEST_FEATURES_FILE, SOURCE_FILE
from lab1.data_contract import (
    SMOKE_RECORDS,
    ContractError,
    serialize_features,
    serialize_payload,
    smoke_payload,
)


def test_serializer_omits_label_and_id_and_keeps_order(cfg, data_dir):
    with (data_dir / SOURCE_FILE).open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if row]
    header, first = rows[0], rows[1]
    index = {name: i for i, name in enumerate(header)}

    record = {feature: float(first[index[feature]]) for feature in cfg.feature_order}
    line = serialize_features(cfg, record)

    assert line.split(",") == [first[index[f]] for f in cfg.feature_order]
    assert len(line.split(",")) == len(cfg.feature_order)
    # The full source row is one column wider on each side (ID and label); the
    # payload must be strictly the middle.
    assert len(first) == len(cfg.feature_order) + 2


def test_serializer_matches_the_generated_inference_file(cfg, data_dir):
    with (data_dir / MODEL_TEST_FEATURES_FILE).open(newline="", encoding="utf-8") as handle:
        file_rows = [row for row in csv.reader(handle) if row]
    with (data_dir / SOURCE_FILE).open(newline="", encoding="utf-8") as handle:
        source = [row for row in csv.reader(handle) if row]
    index = {name: i for i, name in enumerate(source[0])}
    by_features = {",".join(r[index[f]] for f in cfg.feature_order) for r in source[1:]}

    for row in file_rows[:50]:
        assert ",".join(row) in by_features


def test_dictionary_order_does_not_change_the_payload(cfg):
    forward = dict(SMOKE_RECORDS[0]["features"])
    reversed_insertion = {k: forward[k] for k in reversed(list(forward))}
    assert serialize_features(cfg, forward) == serialize_features(cfg, reversed_insertion)


def test_missing_feature_is_rejected(cfg):
    incomplete = dict(SMOKE_RECORDS[0]["features"])
    incomplete.pop(cfg.feature_order[0])
    with pytest.raises(ContractError, match="missing features"):
        serialize_features(cfg, incomplete)


def test_label_in_the_payload_is_rejected(cfg):
    leaking = dict(SMOKE_RECORDS[0]["features"]) | {cfg.label: 1}
    with pytest.raises(ContractError, match="must not carry"):
        serialize_features(cfg, leaking)


def test_id_in_the_payload_is_rejected(cfg):
    leaking = dict(SMOKE_RECORDS[0]["features"]) | {cfg.id_column: 7}
    with pytest.raises(ContractError, match="must not carry"):
        serialize_features(cfg, leaking)


def test_unknown_column_is_rejected(cfg):
    extra = dict(SMOKE_RECORDS[0]["features"]) | {"favourite_colour": 1}
    with pytest.raises(ContractError, match="unknown columns"):
        serialize_features(cfg, extra)


def test_non_finite_value_is_rejected(cfg):
    broken = dict(SMOKE_RECORDS[0]["features"]) | {"monthly_charges": float("nan")}
    with pytest.raises(ContractError, match="finite"):
        serialize_features(cfg, broken)


def test_fractional_value_in_an_integer_column_is_rejected(cfg):
    broken = dict(SMOKE_RECORDS[0]["features"]) | {"tenure_months": 12.5}
    with pytest.raises(ContractError, match="integral"):
        serialize_features(cfg, broken)


def test_empty_payload_is_rejected(cfg):
    with pytest.raises(ContractError, match="empty payload"):
        serialize_payload(cfg, [])


def test_smoke_payload_is_stable_and_well_shaped(cfg):
    names, body = smoke_payload(cfg)
    assert names == ["high_risk", "low_risk"]
    assert body == smoke_payload(cfg)[1]
    lines = body.split("\n")
    assert len(lines) == 2
    assert all(len(line.split(",")) == len(cfg.feature_order) for line in lines)


def test_smoke_records_are_inside_the_contract_bounds(cfg):
    for record in SMOKE_RECORDS:
        for feature, value in record["features"].items():
            low, high = cfg.bounds[feature]
            assert low <= value <= high, f"{record['name']}.{feature}"


def test_high_risk_record_is_really_riskier_under_the_generator(cfg):
    """Guards the smoke assertion itself: the two records must differ in risk."""
    import math

    from lab1.dataset import DGP

    def probability(features: dict[str, float]) -> float:
        logit = (
            DGP["intercept"]
            + DGP["tenure_months"] * features["tenure_months"]
            + DGP["support_calls_90d"] * features["support_calls_90d"]
            + DGP["payment_delay_days"] * features["payment_delay_days"]
            + DGP["monthly_charges"] * (features["monthly_charges"] - DGP["monthly_charges_center"])
            + DGP["annual_contract"] * features["annual_contract"]
            + DGP["premium_plan"] * features["premium_plan"]
            + DGP["usage_score"] * (features["usage_score"] - DGP["usage_score_center"])
        )
        return 1.0 / (1.0 + math.exp(-logit))

    high = probability(SMOKE_RECORDS[0]["features"])
    low = probability(SMOKE_RECORDS[1]["features"])
    assert high > 0.9
    assert low < 0.1
