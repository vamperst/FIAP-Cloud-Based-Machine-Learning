import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab1.config import DATA_DIR, load_config, load_schema  # noqa: E402
from lab1.dataset import write_dataset  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def schema():
    return load_schema()


@pytest.fixture(scope="session")
def data_dir(cfg, tmp_path_factory):
    """Generate the dataset once into a temp dir.

    The tests must not depend on whatever happens to be in artifacts/ - a stale
    dataset passing the contract would be the worst possible false positive.
    """
    target = tmp_path_factory.mktemp("dataset")
    write_dataset(cfg, target)
    return target


@pytest.fixture(scope="session")
def repo_root():
    return ROOT
