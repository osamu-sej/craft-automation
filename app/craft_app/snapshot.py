"""本家資料のスナップショット（requirements.md §10-C）。scripts/snapshot-upstream.sh の Python 版。

bash・curl・jq・git がなくても動くようにした（Windows 向け）。出力はシェル版と同じ内容で、
`docs/upstream-snapshot/<tag>/` に「文書・CLI/MCP のソース・コマンド台帳・MCP ツール一覧・リリース asset 一覧」を固定する。
ディレクトリは毎回作り直し、版の混在を防ぐ。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import requests

from . import mcp, photocraft, releases

RAW = f"https://raw.githubusercontent.com/{photocraft.UPSTREAM}"
API = f"https://api.github.com/repos/{photocraft.UPSTREAM}"

# scripts/snapshot-upstream.sh の FILES と同じ
FILES = [
    "README.md", "AGENTS.md", "docs/control-protocol.md", "docs/parity.md", "docs/roadmap.md",
    "apps/photocraft-cli/src/lib.rs",  # CLI 定義・batch のアクションリスト形式（parse_actions）
    "crates/automation/src/server.rs",  # MCP ツール定義
    "LICENSE-MIT", "LICENSE-APACHE", "NOTICE",
]


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def commit_sha(tag: str) -> str:
    """タグが指すコミット。API → git ls-remote の順に試す。取れなければ空文字。"""
    try:
        r = requests.get(f"{API}/commits/{tag}", headers={"Accept": "application/vnd.github+json", "User-Agent": "craft-automation"}, timeout=releases.TIMEOUT)
        if r.status_code == 200:
            return r.json()["sha"]
    except (requests.RequestException, KeyError, ValueError):
        pass
    try:
        out = subprocess.run(["git", "ls-remote", photocraft.GIT_URL, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                             capture_output=True, text=True, timeout=60, check=True).stdout.split("\n")
        shas = {ln.split("\t")[1]: ln.split("\t")[0] for ln in out if "\t" in ln}
        return shas.get(f"refs/tags/{tag}^{{}}") or shas.get(f"refs/tags/{tag}", "")
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def source_md(tag: str, sha: str) -> str:
    where = f"{photocraft.GIT_URL}/tree/{tag}" + (f" （commit `{sha}`）" if sha else "（commit を取得できませんでした）")
    return f"""# 本家スナップショット {tag}

- 取得元: {where}
- 生成: `scripts/snapshot-upstream.sh {tag}` またはアプリの「ピン更新」（手で編集しない）
- ライセンス: 本家は MIT OR Apache-2.0。同梱の LICENSE-MIT / LICENSE-APACHE / NOTICE を参照

| ファイル | 内容 |
|---|---|
| README.md, AGENTS.md, docs/*.md | 本家文書（{tag} 時点） |
| apps/photocraft-cli/src/lib.rs | CLI 定義。`parse_actions` が batch のアクションリスト形式の正本 |
| crates/automation/src/server.rs | MCP ツール定義 |
| generated/version.txt | `photocraft-cli --version` |
| generated/commands.json | `photocraft-cli commands --json`（コマンド台帳・params 書式） |
| generated/mcp-tools.json | `photocraft-cli mcp` の tools/list 結果 |
| generated/release-assets.txt | リリースの SHA256SUMS.txt（asset 名の一覧） |
"""


def create(tag: str, cli: Path, root: Path) -> Path:
    """`<root>/<tag>/` を作り直す。途中で失敗したら、既存のスナップショットはそのまま残す。"""
    final = root / tag
    tmp = root / f".{tag}.partial"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for f in FILES:
            with releases._get(f"{RAW}/{tag}/{f}") as r:
                _write(tmp / f, r.content)
        with releases._get(photocraft.asset_url(tag, photocraft.CHECKSUMS)) as r:
            _write(tmp / "generated" / "release-assets.txt", r.content)
        _write(tmp / "generated" / "version.txt", (photocraft.cli_version(cli) + "\n").encode("utf-8"))
        cmds = subprocess.run(photocraft.commands_args(cli), capture_output=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if cmds.returncode != 0:
            raise RuntimeError(f"commands --json が終了コード {cmds.returncode} で失敗: {cmds.stderr.decode('utf-8', 'replace').strip()}")
        _write(tmp / "generated" / "commands.json", cmds.stdout)
        probe = mcp.probe(cli, mcp.server_args(), timeout=60)
        _write(tmp / "generated" / "mcp-tools.json", (json.dumps(probe.tools, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        _write(tmp / "SOURCE.md", source_md(tag, commit_sha(tag)).encode("utf-8"))
        shutil.rmtree(final, ignore_errors=True)
        tmp.rename(final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return final
