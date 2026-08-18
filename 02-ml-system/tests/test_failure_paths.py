"""Failure paths.

A gate that only ever passes is decoration. Each test here corrupts one thing and
asserts the corresponding check turns red, so the contract's authority is itself
under test.
"""

from __future__ import annotations

import csv
import json
import shutil

import pytest
from botocore.exceptions import NoCredentialsError

from lab1 import aws_helpers as aws
from lab1.config import (
    MANIFEST_FILE,
    MODEL_TEST_FEATURES_FILE,
    MODEL_TRAIN_FILE,
    SOURCE_FILE,
    TEST_LABELS_FILE,
)
from lab1.data_contract import validate


@pytest.fixture
def corrupt_dir(data_dir, tmp_path):
    """A writable copy of a valid dataset, ready to be broken."""
    target = tmp_path / "corrupt"
    shutil.copytree(data_dir, target)
    return target


def failed_names(cfg, schema, directory) -> set[str]:
    return {check.name for check in validate(cfg, schema, directory).failed}


def test_missing_file_is_detected(cfg, schema, corrupt_dir):
    (corrupt_dir / MODEL_TRAIN_FILE).unlink()
    assert "files.present" in failed_names(cfg, schema, corrupt_dir)


def test_header_added_to_a_model_file_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / MODEL_TRAIN_FILE
    body = path.read_text(encoding="utf-8")
    path.write_text(",".join([cfg.label, *cfg.feature_order]) + "\n" + body, encoding="utf-8")
    failures = failed_names(cfg, schema, corrupt_dir)
    assert f"{MODEL_TRAIN_FILE}.no_header" in failures


def test_label_leaking_into_the_inference_file_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / MODEL_TEST_FEATURES_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows([["1", *row] for row in rows])
    failures = failed_names(cfg, schema, corrupt_dir)
    assert f"{MODEL_TEST_FEATURES_FILE}.column_count" in failures
    assert f"{MODEL_TEST_FEATURES_FILE}.no_label_column" in failures


def test_out_of_range_feature_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / SOURCE_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    index = rows[0].index("monthly_charges")
    rows[1][index] = "999999.00"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    failures = failed_names(cfg, schema, corrupt_dir)
    assert "source.numeric_ranges" in failures
    assert "manifest.fingerprints_match_files" in failures


def test_duplicate_observation_id_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / SOURCE_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    rows[2][0] = rows[1][0]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    assert "source.unique_observation_id" in failed_names(cfg, schema, corrupt_dir)


def test_non_binary_label_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / SOURCE_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    rows[1][-1] = "2"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    assert "source.label_binary" in failed_names(cfg, schema, corrupt_dir)


def test_empty_value_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / SOURCE_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    rows[1][rows[0].index("usage_score")] = ""
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    assert "source.no_nan_or_inf" in failed_names(cfg, schema, corrupt_dir)


def test_tampered_file_breaks_its_fingerprint(cfg, schema, corrupt_dir):
    path = corrupt_dir / MODEL_TRAIN_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("\n", "\n", 1) + "0,1,1,1,1,1,1,1\n", encoding="utf-8")
    assert "manifest.fingerprints_match_files" in failed_names(cfg, schema, corrupt_dir)


def test_manifest_row_count_lie_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["splits"]["train"]["rows"] = 1
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    assert "splits.train.rows_match_manifest" in failed_names(cfg, schema, corrupt_dir)


def test_test_label_disagreeing_with_source_is_detected(cfg, schema, corrupt_dir):
    path = corrupt_dir / TEST_LABELS_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    rows[1][1] = "0" if rows[1][1] == "1" else "1"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    assert "test_labels.consistent_with_source" in failed_names(cfg, schema, corrupt_dir)


def test_truncated_split_breaks_the_partition(cfg, schema, corrupt_dir):
    path = corrupt_dir / MODEL_TRAIN_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-10]) + "\n", encoding="utf-8")
    failures = failed_names(cfg, schema, corrupt_dir)
    assert "splits.partition_source" in failures
    assert "splits.train.rows_match_manifest" in failures


# --------------------------------------------------------------------------- #
# AWS-facing guards, exercised without touching AWS
# --------------------------------------------------------------------------- #


def test_probability_outside_the_unit_interval_is_rejected():
    with pytest.raises(aws.AwsError, match=r"out of \[0,1\]"):
        aws.parse_csv_probabilities("1.4")


def test_wrong_number_of_probabilities_is_rejected():
    with pytest.raises(aws.AwsError, match="probabilities for"):
        aws.parse_csv_probabilities("0.1\n0.2", expected=3)


def test_probabilities_parse_from_both_response_shapes():
    assert aws.parse_csv_probabilities("0.10\n0.90", expected=2) == [0.10, 0.90]
    assert aws.parse_csv_probabilities("0.10,0.90", expected=2) == [0.10, 0.90]


def test_malformed_s3_uri_is_rejected():
    with pytest.raises(aws.AwsError, match="not an S3 URI"):
        aws.split_s3_uri("https://example.com/model.tar.gz")
    with pytest.raises(aws.AwsError, match="missing bucket or key"):
        aws.split_s3_uri("s3://only-a-bucket")


def test_s3_uri_splits_into_bucket_and_key():
    assert aws.split_s3_uri("s3://b/output/x/model.tar.gz") == ("b", "output/x/model.tar.gz")


def test_missing_terraform_output_explains_the_next_step():
    with pytest.raises(aws.AwsError, match="make apply"):
        aws.require_output({"endpoint_name": ""}, "endpoint_name")


def test_region_mismatch_is_refused(monkeypatch):
    class FakeSession:
        region_name = "us-west-2"

    monkeypatch.setattr(aws.boto3.session, "Session", lambda **kwargs: FakeSession())
    with pytest.raises(aws.AwsError, match="requires 'us-east-1'"):
        aws.make_session("us-east-1")


def test_missing_credentials_points_at_the_academy_session():
    class SessionWithoutCredentials:
        region_name = "us-east-1"

        def client(self, service, **kwargs):
            raise NoCredentialsError()

    with pytest.raises(aws.AwsError, match="reopen the lab"):
        aws.whoami(SessionWithoutCredentials())


def test_permuted_feature_order_breaks_the_payload_roundtrip(cfg, schema, corrupt_dir):
    """Feature order drift in the inference file must not pass silently.

    A headerless numeric file gives the reader no names to check, so the guard is
    the roundtrip: the contract re-serialises source.csv through the single
    serializer and demands byte equality with the file that goes to the endpoint.
    """
    path = corrupt_dir / MODEL_TEST_FEATURES_FILE
    rows = [row for row in csv.reader(path.read_text(encoding="utf-8").splitlines()) if row]
    swapped = [[row[1], row[0], *row[2:]] for row in rows]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(swapped)
    assert "payload.roundtrip_matches_file" in failed_names(cfg, schema, corrupt_dir)
