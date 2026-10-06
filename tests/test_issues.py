import re

import pytest
import requests

from craft_app import issues, secrets, settings, upstream


class Resp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data if data is not None else {}

    def json(self):
        return self._data


class FakeSession:
    """GitHub の Issue / ラベル API の最小の偽物。呼び出しを記録する。"""

    def __init__(self, existing=(), label=True, post_status=201, get_status=200):
        self.issues = [{"number": 10 + i, "title": t, "html_url": f"https://github.com/o/r/issues/{10 + i}"} for i, t in enumerate(existing)]
        self.issues.append({"number": 99, "title": "ある PR", "html_url": "x", "pull_request": {}})
        self.label, self.post_status, self.get_status = label, post_status, get_status
        self.calls = []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(("get", url, headers, params))
        if url.endswith("/labels/upstream"):
            return Resp(200 if self.label else 404)
        if url.endswith("/issues"):
            return Resp(self.get_status, self.issues if params["page"] == 1 else [])
        return Resp(404)

    def post(self, url, headers=None, timeout=None, json=None):
        self.calls.append(("post", url, headers, json))
        if url.endswith("/labels"):
            self.label = True
            return Resp(201)
        n = 100 + len([c for c in self.calls if c[0] == "post" and c[1].endswith("/issues")])
        url = f"https://github.com/o/r/issues/{n}"
        if self.post_status == 201:  # 本物と同じく、起票した Issue は次の一覧に出てくる
            self.issues.append({"number": n, "title": json["title"], "html_url": url})
        return Resp(self.post_status, {"number": n, "html_url": url})


def gh(session):
    return issues.GitHub("o/r", "SECRET-TOKEN", session)


def test_titles_match_the_workflows(repo_root):
    """ワークフローとアプリの件名が一致する（ずれると重複排除が効かず、二重に起票される）。"""
    watch = (repo_root / ".github/workflows/upstream-watch.yml").read_text(encoding="utf-8")
    smoke = (repo_root / ".github/workflows/smoke.yml").read_text(encoding="utf-8")
    fmt = lambda src, key: re.search(rf'TITLE="(\[upstream\] {key}[^"]*)"', src).group(1)  # noqa: E731
    assert fmt(watch, "release").replace("$LATEST", "v0.2.0").replace("$PIN", "v0.1.1") == issues.release_issue("v0.1.1", "v0.2.0", 70).title
    assert fmt(watch, r"\$p").replace("$p", "README.md").replace("$S7", "abcdef0") == issues.watched_issue("README.md", "abcdef0123").title
    assert fmt(smoke, "smoke").replace("$TAG", "v0.2.0") == issues.smoke_issue("v0.2.0", []).title
    assert f"--label {issues.LABEL}" in watch  # ラベル名も同じ


def test_release_body_has_links_and_steps():
    body = issues.release_issue("v0.1.1", "v0.2.0", 70).body
    assert "releases/tag/v0.2.0" in body and "compare/v0.1.1...v0.2.0 （コミット数: 70）" in body
    assert "- [ ] .photocraft-version を更新" in body
    assert "コミット数: ?" in issues.release_issue("v0.1.1", "v0.2.0", None).body


def test_watched_body_names_the_sha_file():
    i = issues.watched_issue("docs/control-protocol.md", "a" * 40)
    assert i.title == "[upstream] docs/control-protocol.md changed (aaaaaaa)"
    assert ".upstream/docs_control-protocol_md.sha に `" + "a" * 40 + "` を記録" in i.body


def test_pending_from_status():
    c = upstream.Commit("b" * 40, "2026-10-05T00:00:00Z")
    s = upstream.Status("t", "v0.1.1", "v0.2.0", newer=["v0.2.0"], commits=70)
    s.watched = [upstream.Watched("a.md", "b" * 40, c), upstream.Watched("b.md", None, c), upstream.Watched("c.md", "old", c), upstream.Watched("d.md", None, None)]
    titles = [i.title for i in issues.pending(s)]
    assert titles == ["[upstream] release v0.2.0 (pinned: v0.1.1)", "[upstream] b.md changed (bbbbbbb)", "[upstream] c.md changed (bbbbbbb)"]
    assert issues.pending(upstream.Status("t", "v0.2.0", "v0.2.0")) == []


def test_sync_creates_only_missing_and_never_twice():
    a, b = issues.Issue("[upstream] A", "x"), issues.Issue("[upstream] B", "y")
    s = FakeSession(existing=["[upstream] A"], label=False)
    res = issues.sync(gh(s), [a, b, b])
    assert [(r.title, r.created) for r in res] == [("[upstream] A", False), ("[upstream] B", True), ("[upstream] B", False)]
    assert res[0].number == 10 and res[1].number == 101 and res[2].number == res[1].number
    posts = [c for c in s.calls if c[0] == "post"]
    assert [p[1].rsplit("/", 1)[-1] for p in posts] == ["labels", "issues"]  # ラベルを作ってから 1 件だけ起票
    assert posts[1][3] == {"title": "[upstream] B", "body": "y", "labels": ["upstream"]}


def test_sync_with_nothing_does_not_call_github():
    s = FakeSession()
    assert issues.sync(gh(s), []) == [] and s.calls == []


def test_pull_requests_are_not_issues():
    s = FakeSession(existing=[])
    assert "ある PR" not in gh(s).existing()


@pytest.mark.parametrize("status", [401, 403])
def test_permission_errors_are_explained_without_the_token(status):
    s = FakeSession(get_status=status)
    with pytest.raises(issues.GitHubError) as e:
        issues.sync(gh(s), [issues.Issue("t", "b")])
    assert "権限" in str(e.value) and "SECRET-TOKEN" not in str(e.value)


def test_create_failure_and_network_error():
    with pytest.raises(issues.GitHubError, match="HTTP 422"):
        issues.sync(gh(FakeSession(post_status=422)), [issues.Issue("t", "b")])

    class Down(FakeSession):
        def get(self, *a, **k):
            raise requests.ConnectionError("boom")

    with pytest.raises(issues.GitHubError, match="接続できません") as e:
        issues.sync(gh(Down()), [issues.Issue("t", "b")])
    assert "SECRET-TOKEN" not in str(e.value)


def test_token_is_only_sent_as_a_header():
    s = FakeSession()
    issues.sync(gh(s), [issues.Issue("t", "b")])
    assert all(c[2]["Authorization"] == "Bearer SECRET-TOKEN" for c in s.calls)
    assert not any("SECRET-TOKEN" in str(c[1]) + str(c[3]) for c in s.calls)  # URL・本文には出ない


# ---- トークンの保管と設定 ------------------------------------------------------------


class FakeKeyring:
    priority = 5

    def __init__(self):
        self.store = {}

    def get_keyring(self):
        return self

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        self.store.pop((service, account), None)


def test_token_lives_in_the_keychain_and_env_wins(monkeypatch, tmp_path):
    kr = FakeKeyring()
    monkeypatch.setattr(secrets, "keyring", kr)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert secrets.get_token() == (None, "未設定")
    secrets.save_token("  ghp_abc \n")
    assert secrets.get_token() == ("ghp_abc", "OS のキーチェーン")
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert secrets.get_token() == ("env-token", "環境変数 GITHUB_TOKEN")
    monkeypatch.delenv("GITHUB_TOKEN")
    secrets.delete_token()
    assert secrets.get_token()[0] is None
    with pytest.raises(ValueError):
        secrets.save_token("  ")
    # アプリデータ領域のどこにも書かない（キーチェーンだけ）
    assert not list(tmp_path.rglob("*"))


def test_without_keychain_only_env_is_used(monkeypatch):
    monkeypatch.setattr(secrets, "keyring", None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert secrets.keychain_available() is False and secrets.get_token()[0] is None
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        secrets.save_token("x")
    secrets.delete_token()  # 何も起きない


def test_settings_round_trip_and_unknown_keys(tmp_path):
    p = tmp_path / "data" / "settings.json"
    assert settings.load(p) == settings.DEFAULTS
    settings.save(p, {"issue_repo": "o/r", "auto_issue": True, "token": "must-not-be-saved"})
    assert settings.load(p) == {"issue_repo": "o/r", "auto_issue": True}
    assert "must-not-be-saved" not in p.read_text(encoding="utf-8")
    p.write_text("{broken", encoding="utf-8")
    assert settings.load(p) == settings.DEFAULTS  # 壊れていても起動できる


@pytest.mark.parametrize("slug,ok", [("osamu-sej/craft-automation", True), ("a/b.c-d_e", True), ("a", False), ("a/b/c", False), ("a b/c", False), ("", False)])
def test_check_slug(slug, ok):
    assert (settings.check_slug(slug) is None) == ok


@pytest.mark.parametrize("url", ["https://github.com/osamu-sej/craft-automation", "https://github.com/osamu-sej/craft-automation.git",
                                 "git@github.com:osamu-sej/craft-automation.git", "https://user@github.com/osamu-sej/craft-automation.git"])
def test_origin_slug_from_git_config(tmp_path, url):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text(f'[core]\n\tbare = false\n[remote "upstream"]\n\turl = https://github.com/x/y\n[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n', encoding="utf-8")
    assert settings.origin_slug(tmp_path) == "osamu-sej/craft-automation"


def test_origin_slug_missing(tmp_path):
    assert settings.origin_slug(tmp_path) is None
