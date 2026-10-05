"""作業ディレクトリ（craft-automation リポジトリ）とアプリデータ領域の場所。

正本はリポジトリのファイル（requirements.md FR-09）。アプリ固有の状態は実行履歴だけで、
アプリデータ領域の SQLite に置く（§5）。
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


def default_repo_root() -> Path:
    env = os.environ.get("CRAFT_REPO")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]  # app/craft_app/paths.py → リポジトリ直下


def app_data_dir() -> Path:
    env = os.environ.get("CRAFT_APP_DATA")
    if env:
        return Path(env).expanduser()
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "craft-automation"
    if system == "Windows":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "craft-automation"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "craft-automation"


@dataclass(frozen=True)
class Repo:
    root: Path

    @property
    def actions_dir(self) -> Path:
        return self.root / "actions"

    @property
    def pin_file(self) -> Path:
        return self.root / ".photocraft-version"

    @property
    def bin_dir(self) -> Path:
        return self.root / ".bin"  # .gitignore 済み。版ごとに .bin/<tag>/ へ展開する

    @property
    def snapshot_dir(self) -> Path:
        return self.root / "docs" / "upstream-snapshot"

    def pinned(self) -> str | None:
        try:
            tag = self.pin_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return tag or None

    def resolve(self, text: str) -> Path:
        """入力欄のパス。前後の引用符（Windows の「パスのコピー」）を外し、相対はリポジトリ基準。"""
        text = text.strip().strip('"').strip("'")
        p = Path(text).expanduser()
        return p if p.is_absolute() else self.root / p
