"""Lifecycle trap.

The most expensive failure mode of this lab is a smoke test that fails *after* the
endpoint is up and takes the cleanup down with it - the endpoint keeps billing and
nobody notices until the budget report. `make e2e` guards that with a shell trap,
and a guard nobody tested is a guess.

The test drives the real Makefile with stubbed `TF` and `PYTHON`, in a temporary
directory, so the orchestration is exercised with no AWS call and no cost: does the
trap still run destroy + verify-clean when the post-deploy step fails, and is the
original exit code preserved?
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

MAKE = shutil.which("make")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(not (MAKE and BASH), reason="needs make and bash")

# Stubs record what they were asked to do and exit 0, except predict.py, which
# fails the way a broken model contract would fail after a successful deploy.
STUB_TF = """#!/usr/bin/env bash
echo "tf $*" >> "$TRACE"
exit 0
"""

STUB_PY = """#!/usr/bin/env bash
echo "py $*" >> "$TRACE"
for arg in "$@"; do
  case "$arg" in
    *predict.py) echo "simulated post-deploy failure" >&2; exit 3 ;;
  esac
done
exit 0
"""


@pytest.fixture
def sandbox(tmp_path, repo_root):
    """A throwaway copy of the Makefile: the trap must never touch the real repo."""
    shutil.copy(repo_root / "Makefile", tmp_path / "Makefile")
    (tmp_path / "terraform").mkdir()
    (tmp_path / "scripts").mkdir()

    for name, body in (("tf", STUB_TF), ("py", STUB_PY)):
        stub = tmp_path / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    return tmp_path


def run_e2e(sandbox, **env_extra) -> tuple[int, str]:
    trace = sandbox / "trace.txt"
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "TRACE": str(trace),
        **env_extra,
    }
    completed = subprocess.run(
        [MAKE, "e2e", f"TF={sandbox / 'tf'}", f"PYTHON={sandbox / 'py'}"],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.returncode, trace.read_text(encoding="utf-8") if trace.exists() else ""


def test_cleanup_runs_after_a_post_deploy_failure(sandbox):
    code, trace = run_e2e(sandbox)

    assert code != 0, "a failed smoke test must fail the lifecycle"
    assert "py scripts/predict.py" in trace, "the failure has to happen after deploy"
    assert "tf -chdir=terraform destroy" in trace, "the trap did not destroy"
    assert "py scripts/verify_clean.py" in trace, "the trap did not verify the cleanup"

    # Order matters: cleanup after the failure, not before it.
    lines = trace.splitlines()
    assert lines.index("py scripts/predict.py") < next(
        i for i, line in enumerate(lines) if "destroy" in line
    )


def test_keep_resources_skips_cleanup_and_warns(sandbox):
    code, trace = run_e2e(sandbox, KEEP_RESOURCES="1")

    assert code != 0
    assert "destroy" not in trace, "KEEP_RESOURCES=1 must leave the resources alone"
    assert "verify_clean.py" not in trace
