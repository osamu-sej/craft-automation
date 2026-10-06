"""アプリの設定（アプリデータ領域の settings.json）。秘密（トークン）は含めない。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

DEFAULTS = {
    "issue_repo": "",  # Issue を起票する "owner/repo"。空なら origin から推定する
    "auto_issue": False,  # 本家の確認で見つけた更新を自動で起票する（既定はオフ）
}
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def save(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: values.get(k, d) for k, d in DEFAULTS.items()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_slug(slug: str) -> str | None:
    return None if _SLUG.match(slug.strip()) else "owner/repo の形で指定してください（例: osamu-sej/craft-automation）"


_REMOTE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?\s*$")


def origin_slug(repo_root: Path) -> str | None:
    """.git/config の origin から owner/repo を読む（git コマンドは使わない）。ZIP で入れた場合は None。"""
    cfg = repo_root / ".git" / "config"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_origin = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_origin = s.replace(" ", "") == '[remote"origin"]'
        elif in_origin and s.startswith("url"):
            m = _REMOTE.search(s.split("=", 1)[1].strip())
            if m:
                return f"{m[1]}/{m[2]}"
    return None
