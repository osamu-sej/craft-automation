import os
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


def write_mock_cli(path: Path, fail: bool = False) -> Path:
    """tests/mock_cli.py を、この OS で直接起動できる photocraft-cli として置く。fail=True は全ファイルで失敗する。"""
    mock = Path(__file__).resolve().parent / "mock_cli.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = path.with_suffix(".bat")
        env = "@set MOCK_FAIL=1\n" if fail else ""
        path.write_text(f'{env}@"{sys.executable}" "{mock}" %*\n', encoding="utf-8")  # テキストモードで CRLF になる
    else:
        env = "MOCK_FAIL=1 " if fail else ""
        path.write_text(f'#!/bin/sh\n{env}exec "{sys.executable}" "{mock}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path
