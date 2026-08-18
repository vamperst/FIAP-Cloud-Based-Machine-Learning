"""Config drift.

Some values must exist in both Terraform and Python: the bucket prefix (so
verify-clean can find the bucket after state is gone) and the region. Nothing
enforces that automatically, so these tests read the .tf source and compare.
"""

from __future__ import annotations

import json
import re

TF_VARIABLES = "terraform/variables.tf"


def default_of(source: str, variable: str) -> str:
    block = re.search(
        rf'variable\s+"{variable}"\s*\{{(.*?)\n\}}', source, re.DOTALL
    )
    assert block, f"variable {variable!r} not found in {TF_VARIABLES}"
    default = re.search(r'default\s*=\s*"([^"]*)"', block.group(1))
    assert default, f"variable {variable!r} has no string default"
    return default.group(1)


def test_bucket_prefix_matches_terraform(cfg, repo_root):
    source = (repo_root / TF_VARIABLES).read_text(encoding="utf-8")
    assert cfg.bucket_prefix == default_of(source, "project_prefix")


def test_region_matches_terraform(cfg, repo_root):
    source = (repo_root / TF_VARIABLES).read_text(encoding="utf-8")
    assert cfg.region == default_of(source, "region")


def test_execution_role_matches_terraform(cfg, repo_root):
    source = (repo_root / TF_VARIABLES).read_text(encoding="utf-8")
    assert cfg.execution_role_name == default_of(source, "execution_role_name")


def test_pinned_versions_are_exact(repo_root):
    versions = (repo_root / "terraform/versions.tf").read_text(encoding="utf-8")
    assert 'required_version = "= 1.15.8"' in versions
    assert 'version = "= 6.60.0"' in versions


def test_training_image_is_the_managed_xgboost_171(repo_root):
    source = (repo_root / TF_VARIABLES).read_text(encoding="utf-8")
    expected = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:1.7-1"
    assert default_of(source, "training_image") == expected


def test_schema_and_config_agree_on_the_feature_order(cfg, schema):
    assert schema["feature_order"] == cfg.feature_order
    assert schema["serving"]["column_count"] == len(cfg.feature_order)
    assert schema["training"]["column_count"] == len(cfg.feature_order) + 1


def test_every_feature_has_bounds_and_a_schema_entry(cfg, schema):
    for feature in cfg.feature_order:
        assert feature in cfg.bounds, feature
        assert feature in schema["columns"], feature
        assert schema["columns"][feature]["role"] == "feature"


def test_serving_never_carries_the_label(cfg, schema):
    assert schema["serving"]["label_present"] is False
    assert cfg.label not in schema["feature_order"]
    assert cfg.id_column not in schema["feature_order"]


def test_acceptance_thresholds_are_present_and_sane(cfg):
    acceptance = cfg.acceptance
    assert 0 < acceptance["roc_auc_min"] < 1
    assert 0 < acceptance["f1_min"] < 1
    assert acceptance["must_beat_majority_accuracy"] is True
    assert cfg.decision_threshold == 0.5


def test_gitignore_covers_the_required_paths(repo_root):
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in (
        ".env",
        ".env.*",
        ".aws/",
        "*.pem",
        "*.ppk",
        "terraform.tfstate",
        "terraform.tfstate.*",
        ".terraform/",
        "artifacts/",
        "build/",
        "__pycache__/",
        ".pytest_cache/",
    ):
        assert pattern in ignored, pattern


def test_terraform_lock_is_committed_for_the_classroom_platforms(repo_root):
    """`zh:` checksums are registry-signed and platform independent.

    They are what lets `terraform init` succeed on a macOS laptop and on the
    linux_amd64 Codespace from the same committed lock file. A lock holding only
    an `h1:` hash would break whichever platform did not generate it.
    """
    lock = (repo_root / "terraform/.terraform.lock.hcl").read_text(encoding="utf-8")
    assert 'version     = "6.60.0"' in lock
    assert 'version     = "3.9.0"' in lock
    assert lock.count("zh:") >= 20, "run: terraform providers lock -platform=linux_amd64 ..."


def test_no_credential_ever_reaches_a_tracked_file(repo_root):
    """Cheap guard against the classic accident of pasting Academy credentials."""
    forbidden = re.compile(r"(aws_secret_access_key|aws_session_token|ASIA[0-9A-Z]{16})")
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        if relative.startswith((".venv/", "artifacts/", "terraform/.terraform/", ".git/")):
            continue
        if path.suffix in {".pyc", ".zip", ".gz", ".csv", ".json"} and relative.startswith("artifacts"):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        match = forbidden.search(content)
        # The test file itself names the patterns it forbids.
        assert not match or relative == "tests/test_config_drift.py", f"{relative}: {match}"


def test_dataset_manifest_shape_matches_the_spec_example(cfg, data_dir):
    manifest = json.loads((data_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == cfg.seed
    assert manifest["schema_version"] == cfg.schema_version
    assert manifest["feature_order"] == cfg.feature_order
    assert manifest["label"] == cfg.label
    assert set(manifest["splits"]) == {"train", "validation", "test"}
    for split in manifest["splits"].values():
        assert "rows" in split and "sha256" in split


def test_terraform_declares_only_the_expected_resource_types(repo_root):
    """Academy forbids creating IAM, and nothing here should cost beyond the lab.

    Reading the plan would need credentials, so the guard is the source: any new
    resource type has to be added here deliberately, which makes an accidental
    IAM role, NAT Gateway or EC2 instance a failing test instead of a surprise on
    the invoice.
    """
    allowed = {
        "random_id",
        "aws_s3_bucket",
        "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_object",
        "aws_sagemaker_training_job",
        "aws_sagemaker_model",
        "aws_sagemaker_endpoint_configuration",
        "aws_sagemaker_endpoint",
    }
    declared = set()
    for path in sorted((repo_root / "terraform").glob("*.tf")):
        declared.update(re.findall(r'^resource\s+"([^"]+)"', path.read_text(encoding="utf-8"), re.M))
    assert declared <= allowed, f"unexpected resource types: {sorted(declared - allowed)}"
    assert "aws_iam_role" not in declared, "Academy forbids creating IAM roles"
