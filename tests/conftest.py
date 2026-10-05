import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: 本家リリースを実際に取得して動かす（ネットワーク必須）")


@pytest.fixture
def repo_root() -> Path:
    return ROOT
