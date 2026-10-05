"""PhotoCraft のリリース一覧と、版ごとの取得・検証・展開（requirements.md FR-02）。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import requests

from . import photocraft

TIMEOUT = 30


class DownloadError(RuntimeError):
    """取得失敗。試した URL と HTTP ステータスを持つ（FR-02）。"""

    def __init__(self, url: str, status: int | None, detail: str = ""):
        self.url, self.status = url, status
        super().__init__(f"{url} の取得に失敗しました（HTTP {status if status is not None else '-'}）{': ' + detail if detail else ''}")


@dataclass(frozen=True)
class Release:
    tag: str
    prerelease: bool
    published_at: str = ""


def _version_key(tag: str) -> tuple:
    """`v0.2.0` > `v0.1.1` > `v0.1.1-rc.5`。解釈できないタグは最後。"""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.+))?$", tag)
    if not m:
        return (-1,)
    pre = m[4]
    pre_key = (1,) if pre is None else (0, *[(0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")])
    return (int(m[1]), int(m[2]), int(m[3]), pre_key)


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "craft-automation"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_releases() -> tuple[list[Release], str]:
    """新しい順のリリース一覧と、取得元の説明を返す。

    GitHub API（未認証は 60 回/時）を使い、失敗したら git ls-remote のタグで代用する。
    """
    try:
        r = requests.get(photocraft.RELEASES_API, params={"per_page": 50}, headers=_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            rels = [Release(x["tag_name"], bool(x.get("prerelease")), x.get("published_at") or "") for x in r.json() if not x.get("draft")]
            return sorted(rels, key=lambda x: _version_key(x.tag), reverse=True), "GitHub API"
        api_error = f"GitHub API: HTTP {r.status_code}"
    except requests.RequestException as e:
        api_error = f"GitHub API: {e.__class__.__name__}"
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", photocraft.GIT_URL],
            capture_output=True, text=True, timeout=TIMEOUT, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return [], f"{api_error}。git でも取得できませんでした"
    tags = [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
    rels = [Release(t, "-" in t) for t in tags if _version_key(t) != (-1,)]
    return sorted(rels, key=lambda x: _version_key(x.tag), reverse=True), f"git のタグ（{api_error}）"


def latest(releases: list[Release]) -> str | None:
    """最新版（プレリリースを含む。smoke.yml の latest と同じ扱い）。"""
    return releases[0].tag if releases else None


@dataclass(frozen=True)
class Installed:
    tag: str
    cli: Path


def installed(bin_dir: Path) -> list[Installed]:
    """`.bin/<tag>/` に展開済みで、この OS 向けの CLI がある版（新しい順）。"""
    if not bin_dir.is_dir():
        return []
    found = []
    for d in bin_dir.iterdir():
        if not d.is_dir():
            continue
        try:
            cli = d / photocraft.asset_for(d.name).cli_relpath
        except photocraft.UnsupportedPlatform:
            continue
        if cli.is_file():
            found.append(Installed(d.name, cli))
    return sorted(found, key=lambda x: _version_key(x.tag), reverse=True)


def _get(url: str) -> requests.Response:
    try:
        r = requests.get(url, headers={"User-Agent": "craft-automation"}, timeout=TIMEOUT, stream=True)
    except requests.RequestException as e:
        raise DownloadError(url, None, e.__class__.__name__) from e
    if r.status_code != 200:
        r.close()
        raise DownloadError(url, r.status_code)
    return r


def _safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts


def _extract(archive: Path, kind: str, dest: Path) -> None:
    if kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as tf:
            bad = [m.name for m in tf.getmembers() if not _safe_member(m.name)]
            if bad:
                raise RuntimeError(f"不正なパスを含む asset です: {bad[0]}")
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest, filter="data")
            else:  # pragma: no cover - 古い Python
                tf.extractall(dest)
    else:
        with zipfile.ZipFile(archive) as zf:
            bad = [n for n in zf.namelist() if not _safe_member(n)]
            if bad:
                raise RuntimeError(f"不正なパスを含む asset です: {bad[0]}")
            zf.extractall(dest)


def install(tag: str, bin_dir: Path, progress: Callable[[int, int], None] | None = None) -> Installed:
    """tag の CLI を取得し、SHA256SUMS.txt で検証してから `.bin/<tag>/` に展開する。

    検証に失敗した取得物は削除し、展開先も作らない。
    """
    asset = photocraft.asset_for(tag)
    dest = bin_dir / tag
    tmp = bin_dir / f".{tag}.partial"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        sums_url = photocraft.asset_url(tag, photocraft.CHECKSUMS)
        with _get(sums_url) as r:
            expected = photocraft.checksum_for(r.text, asset.name)
        if expected is None:
            raise DownloadError(sums_url, 200, f"{asset.name} が一覧にありません（この版にこの OS 向けの asset がない可能性）")
        url = photocraft.asset_url(tag, asset.name)
        archive = tmp / asset.name
        h = hashlib.sha256()
        with _get(url) as r, open(archive, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != expected:
            raise RuntimeError(f"{asset.name} の SHA256 が一致しません（期待値 {expected}、実際 {h.hexdigest()}）。取得物は破棄しました")
        _extract(archive, asset.archive, tmp)
        archive.unlink()
        cli = tmp / asset.cli_relpath
        if not cli.is_file():
            raise RuntimeError(f"{asset.name} の中に {asset.cli_relpath} がありません")
        if os.name != "nt":  # zip は実行権限を保持しない
            cli.chmod(cli.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        photocraft.cli_version(cli)  # 動くことを確かめてから確定する
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Installed(tag, dest / asset.cli_relpath)


def uninstall(tag: str, bin_dir: Path) -> None:
    shutil.rmtree(bin_dir / tag, ignore_errors=True)
