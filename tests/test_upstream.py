"""本家更新の検知（FR-05）。git の複製で代用する経路はローカルの git リポジトリを本家に見立てる。"""

import shutil
import subprocess
from pathlib import Path

import pytest

from craft_app import photocraft as pc
from craft_app import releases, upstream

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git が必要")


def test_sha_key_matches_workflow():
    # upstream-watch.yml: echo "$p" | tr '/.' '__'
    assert upstream.sha_key("docs/control-protocol.md") == "docs_control-protocol_md"
    assert upstream.sha_key("apps/photocraft-cli/src/lib.rs") == "apps_photocraft-cli_src_lib_rs"


def test_record_and_status(tmp_path):
    (tmp_path / ".upstream").mkdir()
    (tmp_path / ".upstream/watched-paths.txt").write_text("README.md\n\nAGENTS.md\n", encoding="utf-8")
    assert upstream.watched_paths(tmp_path) == ["README.md", "AGENTS.md"]
    assert upstream.recorded_sha(tmp_path, "README.md") is None
    f = upstream.record_sha(tmp_path, "README.md", "abc")
    assert f.name == "README_md.sha" and f.read_bytes() == b"abc\n"  # ワークフローの $(cat) と一致する
    c = upstream.Commit("abc", "2026-10-05T00:00:00Z")
    assert upstream.Watched("README.md", "abc", c).status == "確認済み"
    assert upstream.Watched("README.md", "old", c).status == "変更あり"
    assert upstream.Watched("README.md", None, c).status == "未記録"
    assert upstream.Watched("README.md", "abc", None).status == "取得失敗"


def test_registry_diff():
    C = pc.Command
    old = {"a": C("a", "", "", '{"x":1}'), "b": C("b", "", "", "{}"), "c": C("c", "", "", '{"k":1,"gone":2}')}
    new = {"a": C("a", "", "", '{"x":1}'), "c": C("c", "", "", '{"k":1}'), "d": C("d", "", "", "{}")}
    d = upstream.diff_registry(old, new)
    assert (d.added, d.removed, [c for c, _, _ in d.changed]) == (["d"], ["b"], ["c"])
    assert d.touches({"a", "b", "c"}) == ["b", "c"]
    assert upstream.removed_keys('{"k":1,"gone":2}', '{"k":1}') == ["gone"]


def test_registry_diff_v011_to_v020(repo_root):
    """スナップショットの v0.2.0 と自分自身の差分は空、grade のコマンドは影響なし。"""
    reg = pc.parse_registry((repo_root / "docs/upstream-snapshot/v0.2.0/generated/commands.json").read_text(encoding="utf-8"))
    d = upstream.diff_registry(reg, reg)
    assert (d.added, d.removed, d.changed) == ([], [], [])


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fake_upstream(tmp_path, monkeypatch):
    """main に README.md と AGENTS.md の変更、タグ v0.1.0 / v0.2.0 を持つ本家もどき。"""
    src = tmp_path / "upstream"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "t")
    (src / "README.md").write_text("1", encoding="utf-8")
    (src / "AGENTS.md").write_text("1", encoding="utf-8")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "one")
    _git(src, "tag", "v0.1.0")
    for i in range(3):
        (src / "README.md").write_text(str(i + 2), encoding="utf-8")
        _git(src, "commit", "-q", "-am", f"readme {i}")
    _git(src, "tag", "v0.2.0")
    monkeypatch.setattr(pc, "GIT_URL", src.as_uri())

    def no_api(*a, **k):
        raise upstream.Unavailable("GitHub API: HTTP 403")

    monkeypatch.setattr(upstream, "_api", no_api)
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v0.2.0", False), releases.Release("v0.1.0", False)], "テスト"))
    return src


def _head(src, path):
    return subprocess.run(["git", "log", "-1", "--format=%H", "--", path], cwd=src, capture_output=True, text=True, check=True).stdout.strip()


@needs_git
def test_check_with_git_fallback(fake_upstream, tmp_path):
    root = tmp_path / "repo"
    (root / ".upstream").mkdir(parents=True)
    (root / ".upstream/watched-paths.txt").write_text("README.md\nAGENTS.md\n", encoding="utf-8")
    upstream.record_sha(root, "AGENTS.md", _head(fake_upstream, "AGENTS.md"))
    mirror = tmp_path / "mirror.git"
    s = upstream.check(root, "v0.1.0", mirror)
    assert s.latest == "v0.2.0" and s.newer == ["v0.2.0"]
    assert s.commits == 3
    assert s.compare_url.endswith("/compare/v0.1.0...v0.2.0")
    assert {w.path: w.status for w in s.watched} == {"README.md": "未記録", "AGENTS.md": "確認済み"}
    assert s.pending == 2  # 新リリース + README.md
    assert any("git の複製" in n for n in s.notes)
    # 確認済みにするとファイルに記録され、ネットワークなしで表示に反映される（受け入れ基準 5）
    readme = next(w for w in s.watched if w.path == "README.md")
    upstream.record_sha(root, "README.md", readme.latest.sha)
    assert upstream.apply_records(s, root).pending == 1
    assert (root / ".upstream/README_md.sha").read_text(encoding="utf-8").strip() == _head(fake_upstream, "README.md")


@needs_git
def test_mirror_follows_new_commits(fake_upstream, tmp_path):
    mirror = tmp_path / "mirror.git"
    first, _ = upstream.latest_commits(["README.md"], mirror)
    (fake_upstream / "README.md").write_text("new", encoding="utf-8")
    _git(fake_upstream, "commit", "-q", "-am", "more")
    second, _ = upstream.latest_commits(["README.md"], mirror)
    assert first["README.md"].sha != second["README.md"].sha == _head(fake_upstream, "README.md")


def test_pinned_is_latest_has_nothing_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v0.2.0", False)], "テスト"))
    s = upstream.check(tmp_path, "v0.2.0", tmp_path / "mirror.git")
    assert (s.newer, s.compare_url, s.pending, s.watched) == ([], None, 0, [])


def test_watcher_keeps_last_error_and_status():
    calls = []

    def run():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return upstream.Status("t", "v1", "v1")

    w = upstream.Watcher(run, auto=False)
    assert w.status is None
    assert w.refresh().pinned == "v1" and w.error is None
    w.refresh()
    assert w.status.pinned == "v1" and "boom" in w.error  # 失敗しても前回の結果は残す


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def test_github_api_path(monkeypatch, tmp_path):
    """GitHub API 経由（_api を差し替えず、requests.get だけを偽物にする）。"""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        if url.endswith("/commits"):
            return _Resp(200, [{"sha": "b" * 40, "commit": {"committer": {"date": "2026-10-05T00:00:00Z"}}}])
        if "/compare/" in url:
            return _Resp(200, {"total_commits": 70})
        return _Resp(404, {})

    monkeypatch.setattr(upstream.requests, "get", fake_get)
    got, src = upstream.latest_commits(["docs/control-protocol.md"], tmp_path / "mirror.git")
    assert src == "GitHub API" and got["docs/control-protocol.md"].sha == "b" * 40
    assert calls[0] == (f"{upstream.API}/commits", {"path": "docs/control-protocol.md", "per_page": 1})
    assert upstream.count_commits("v0.1.1", "v0.2.0", tmp_path / "mirror.git") == 70
    assert calls[-1][0].endswith("/compare/v0.1.1...v0.2.0")
    assert not (tmp_path / "mirror.git").exists()  # API が使えれば git の複製は作らない
