"""本家更新の検知（requirements.md FR-05）。

upstream-watch.yml と同じ判定（新リリース、監視対象ファイルの最新コミットと記録 SHA の比較）を
アプリで行う。記録 SHA はワークフローと同じ `.upstream/<key>.sha` を正本にする（FR-09）。

本家の情報は GitHub API（未認証 60 回/時）で取り、使えなければ commit と tree だけを持つ
ローカルの git 複製（アプリデータ領域）で代用する。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from . import photocraft, releases

TIMEOUT = 30
API = f"https://api.github.com/repos/{photocraft.UPSTREAM}"


def sha_key(path: str) -> str:
    """upstream-watch.yml の `tr '/.' '__'` と同じ。"""
    return path.replace("/", "_").replace(".", "_")


def watched_paths(root: Path) -> list[str]:
    f = root / ".upstream" / "watched-paths.txt"
    if not f.is_file():
        return []
    return [p.strip() for p in f.read_text(encoding="utf-8").splitlines() if p.strip()]


def recorded_sha(root: Path, path: str) -> str | None:
    f = root / ".upstream" / f"{sha_key(path)}.sha"
    try:
        return f.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def record_sha(root: Path, path: str, sha: str) -> Path:
    """確認済みとして記録する（ワークフローの「確認後 .upstream/<key>.sha に記録」と同じ）。"""
    f = root / ".upstream" / f"{sha_key(path)}.sha"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(sha + "\n", encoding="utf-8", newline="\n")
    return f


def commits_url(path: str) -> str:
    return f"https://github.com/{photocraft.UPSTREAM}/commits/main/{path}"


def compare_url(base: str, head: str) -> str:
    return f"https://github.com/{photocraft.UPSTREAM}/compare/{base}...{head}"


# ---- 取得（GitHub API → git 複製） ------------------------------------------------


class Unavailable(RuntimeError):
    pass


def _api(endpoint: str, **params) -> object:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "craft-automation"}
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"{API}/{endpoint}", params=params, headers=h, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise Unavailable(f"GitHub API: {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise Unavailable(f"GitHub API: HTTP {r.status_code}")
    return r.json()


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        raise Unavailable(f"git: {e.__class__.__name__}") from e
    if r.returncode != 0:
        raise Unavailable(f"git {args[0]}: {r.stderr.strip()[:200]}")
    return r.stdout


def sync_mirror(mirror: Path, url: str | None = None) -> Path:
    """本家の commit と tree だけを持つ複製を作る・更新する（ファイル本体は取らない）。"""
    url = url or photocraft.GIT_URL
    if not (mirror / "HEAD").is_file():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--bare", "--filter=blob:none", url, str(mirror))
    _git("fetch", "--quiet", "--prune", "--filter=blob:none", "origin",
         "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*", cwd=mirror)
    return mirror


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str  # ISO 8601


def latest_commits(paths: list[str], mirror: Path) -> tuple[dict[str, Commit], str]:
    """各パスを最後に変えた本家 main のコミット。(結果, 取得元の説明)。"""
    try:
        out = {}
        for p in paths:
            data = _api("commits", path=p, per_page=1)  # 既定ブランチ（upstream-watch.yml と同じ）
            if data:
                out[p] = Commit(data[0]["sha"], data[0]["commit"]["committer"]["date"])
        return out, "GitHub API"
    except Unavailable as e:
        api_error = str(e)
    sync_mirror(mirror)
    out = {}
    for p in paths:
        line = _git("log", "-1", "--format=%H%x09%cI", "main", "--", p, cwd=mirror).strip()
        if line:
            sha, date = line.split("\t")
            out[p] = Commit(sha, date)
    return out, f"git の複製（{api_error}）"


def count_commits(base: str, head: str, mirror: Path) -> int | None:
    """base..head のコミット数（GitHub の compare と同じ）。取れなければ None。"""
    try:
        return int(_api(f"compare/{base}...{head}")["total_commits"])
    except (Unavailable, KeyError, TypeError, ValueError):
        pass
    try:
        if not (mirror / "HEAD").is_file():
            sync_mirror(mirror)
        return int(_git("rev-list", "--count", f"{base}..{head}", cwd=mirror).strip())
    except (Unavailable, ValueError):
        return None


# ---- 判定 ------------------------------------------------------------------------


@dataclass(frozen=True)
class Watched:
    path: str
    recorded: str | None
    latest: Commit | None

    @property
    def status(self) -> str:
        if self.latest is None:
            return "取得失敗"
        if self.recorded is None:
            return "未記録"
        return "確認済み" if self.recorded == self.latest.sha else "変更あり"

    @property
    def pending(self) -> bool:
        return self.status in ("変更あり", "未記録")


@dataclass
class Status:
    checked_at: str
    pinned: str | None
    latest: str | None
    newer: list[str] = field(default_factory=list)  # ピンより新しいリリース（新しい順）
    commits: int | None = None
    watched: list[Watched] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # 取得元・取得できなかったもの

    @property
    def compare_url(self) -> str | None:
        return compare_url(self.pinned, self.latest) if self.pinned and self.latest and self.pinned != self.latest else None

    @property
    def pending(self) -> int:
        """確認待ちの件数（新リリース 1 件 + 監視対象の変更・未記録）。"""
        return (1 if self.newer else 0) + sum(w.pending for w in self.watched)


def check(root: Path, pinned: str | None, mirror: Path) -> Status:
    """本家の状態を取って判定する（ネットワークを使う。画面からは Watcher 経由で呼ぶ）。"""
    s = Status(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), pinned, None)
    rels, src = releases.list_releases()
    s.notes.append(f"リリース: {src}")
    s.latest = releases.latest(rels)
    if pinned and rels:
        keys = [r.tag for r in rels]
        if pinned in keys:
            s.newer = keys[: keys.index(pinned)]
        else:
            s.notes.append(f"ピン {pinned} がリリース一覧にありません")
    if s.newer:
        s.commits = count_commits(pinned, s.latest, mirror)
    paths = watched_paths(root)
    try:
        latest, src = latest_commits(paths, mirror)
        s.notes.append(f"監視対象: {src}")
    except Unavailable as e:
        latest = {}
        s.notes.append(f"監視対象を取得できませんでした（{e}）")
    s.watched = [Watched(p, recorded_sha(root, p), latest.get(p)) for p in paths]
    return s


def apply_records(s: Status, root: Path) -> Status:
    """ファイルの記録 SHA を読み直す（「確認済み」にしたあと、ネットワークなしで表示を更新する）。"""
    s.watched = [Watched(w.path, recorded_sha(root, w.path), w.latest) for w in s.watched]
    return s


class Watcher:
    """起動時と interval ごとに check を実行し、最新の結果を持つ（FR-05 定期チェック）。"""

    def __init__(self, run: Callable[[], Status], interval: float = 24 * 3600, auto: bool = True):
        self._run = run
        self.interval = interval
        self.status: Status | None = None
        self.error: str | None = None
        self.running = False
        self._lock = threading.Lock()
        if auto:
            threading.Thread(target=self._loop, daemon=True).start()

    def refresh(self) -> Status | None:
        with self._lock:
            self.running = True
            try:
                self.status, self.error = self._run(), None
            except Exception as e:  # noqa: BLE001 - 画面に出す
                self.error = f"{e.__class__.__name__}: {e}"
            finally:
                self.running = False
        return self.status

    def _loop(self) -> None:
        while True:
            self.refresh()
            time.sleep(self.interval)


# ---- コマンド台帳の差分 -------------------------------------------------------------


@dataclass
class RegistryDiff:
    added: list[str]
    removed: list[str]
    changed: list[tuple[str, str, str]]  # (id, 旧 params 書式, 新 params 書式)

    def touches(self, used: set[str]) -> list[str]:
        """レシピで使っているコマンドのうち、削除・書式変更されたもの。"""
        hit = set(self.removed) | {c for c, _, _ in self.changed}
        return sorted(used & hit)


def diff_registry(old: dict[str, photocraft.Command], new: dict[str, photocraft.Command]) -> RegistryDiff:
    return RegistryDiff(
        added=sorted(set(new) - set(old)),
        removed=sorted(set(old) - set(new)),
        changed=sorted((k, old[k].params_doc, new[k].params_doc) for k in set(old) & set(new) if old[k].params_doc != new[k].params_doc),
    )


def removed_keys(old_doc: str, new_doc: str) -> list[str]:
    """params 書式から消えたキー（レシピが黙って無視されるようになる候補）。"""
    a, b = photocraft.param_keys(old_doc), photocraft.param_keys(new_doc)
    return sorted((a or set()) - (b or set()))
