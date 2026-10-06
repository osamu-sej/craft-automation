"""GitHub Issue の起票（requirements.md FR-05「Issue 自動起票は Should」）。

件名・本文・ラベルは .github/workflows/upstream-watch.yml と smoke.yml に合わせる。件名で重複排除するので、
ワークフローとアプリのどちらが先に起票しても、同じ更新で Issue が二重にならない。

トークンは Authorization ヘッダーにだけ使い、ログや例外メッセージに出さない。
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from . import photocraft, upstream

API = "https://api.github.com"
LABEL = "upstream"
LABEL_COLOR = "d93f0b"
LABEL_DESC = "本家 storytold/photocraft の更新"
TIMEOUT = 30


@dataclass(frozen=True)
class Issue:
    title: str
    body: str


# ---- 件名と本文（ワークフローと同じ） --------------------------------------------------------


def release_issue(pinned: str, latest: str, commits: int | None) -> Issue:
    up = photocraft.UPSTREAM
    n = "?" if commits is None else commits
    body = (
        "本家に新しいリリースがあります。\n"
        f"- Release: https://github.com/{up}/releases/tag/{latest}\n"
        f"- Diff: https://github.com/{up}/compare/{pinned}...{latest} （コミット数: {n}）\n\n"
        "## 対応手順（docs/upstream-tracking.md）\n"
        "- [ ] smoke (latest) の結果を確認\n"
        "- [ ] リリースノート / control-protocol の差分を確認\n"
        "- [ ] docs/commands.md・actions/ を修正\n"
        "- [ ] .photocraft-version を更新、docs/upgrade-log.md に追記\n"
    )
    return Issue(f"[upstream] release {latest} (pinned: {pinned})", body)


def watched_issue(path: str, sha: str) -> Issue:
    key = upstream.sha_key(path)
    body = (
        f"監視対象 `{path}` に変更があります。\n"
        f"{upstream.commits_url(path)}\n\n"
        f"確認後、.upstream/{key}.sha に `{sha}` を記録してください。"
    )
    return Issue(f"[upstream] {path} changed ({sha[:7]})", body)


def smoke_issue(latest_tag: str, table: list[dict]) -> Issue:
    lines = [f"最新版 {latest_tag} でレシピが失敗しました。破壊的変更の可能性。", ""]
    for row in table:
        cells = " / ".join(f"{k}: {v}" for k, v in row.items() if k != "レシピ")
        lines.append(f"- {row.get('レシピ', '')}: {cells}")
    lines += ["", "アプリのスモークテスト（pinned と latest の比較）の結果です。"]
    return Issue(f"[upstream] smoke failed on latest ({latest_tag})", "\n".join(lines) + "\n")


def pending(status: upstream.Status) -> list[Issue]:
    """本家の確認結果から、起票すべき更新（新リリースと、確認待ちの監視対象）を作る。"""
    out = []
    if status.newer and status.pinned and status.latest:
        out.append(release_issue(status.pinned, status.latest, status.commits))
    for w in status.watched:
        if w.pending and w.latest:
            out.append(watched_issue(w.path, w.latest.sha))
    return out


# ---- GitHub ------------------------------------------------------------------------


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    title: str
    number: int
    url: str
    created: bool  # False は既存（件名が同じ Issue があった）


@dataclass
class GitHub:
    slug: str  # owner/repo
    token: str
    session: object = None  # 省略すると requests.Session()（使う時点で作る。テストでは差し替える）

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def _call(self, method: str, path: str, **kw):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "craft-automation", "Authorization": f"Bearer {self.token}"}
        try:
            r = getattr(self.session, method)(f"{API}/repos/{self.slug}{path}", headers=headers, timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise GitHubError(f"GitHub に接続できません（{e.__class__.__name__}）") from e
        if r.status_code in (401, 403):
            raise GitHubError(f"GitHub が拒否しました（HTTP {r.status_code}）。トークンの権限（Issues の書き込み）と、{self.slug} へのアクセスを確認してください")
        if r.status_code == 404 and method != "get":
            raise GitHubError(f"{self.slug} が見つかりません（HTTP 404）。リポジトリ名とトークンの権限を確認してください")
        return r

    def existing(self) -> dict[str, tuple[int, str]]:
        """upstream ラベルの付いた Issue（開閉とも）の 件名 → (番号, URL)。検索の反映遅れを避けるため一覧で引く。"""
        found: dict[str, tuple[int, str]] = {}
        for page in range(1, 6):
            r = self._call("get", "/issues", params={"labels": LABEL, "state": "all", "per_page": 100, "page": page})
            if r.status_code != 200:
                raise GitHubError(f"Issue の一覧を取れませんでした（HTTP {r.status_code}）")
            items = r.json()
            for it in items:
                if "pull_request" not in it:
                    found.setdefault(it["title"], (it["number"], it["html_url"]))
            if len(items) < 100:
                break
        return found

    def ensure_label(self) -> None:
        r = self._call("get", f"/labels/{LABEL}")
        if r.status_code == 404:
            c = self._call("post", "/labels", json={"name": LABEL, "color": LABEL_COLOR, "description": LABEL_DESC})
            if c.status_code not in (201, 422):  # 422 は同時に作られた場合
                raise GitHubError(f"ラベルを作れませんでした（HTTP {c.status_code}）")
        elif r.status_code != 200:
            raise GitHubError(f"ラベルを確認できませんでした（HTTP {r.status_code}）")

    def create(self, issue: Issue) -> tuple[int, str]:
        r = self._call("post", "/issues", json={"title": issue.title, "body": issue.body, "labels": [LABEL]})
        if r.status_code != 201:
            raise GitHubError(f"Issue を作れませんでした（HTTP {r.status_code}）")
        data = r.json()
        return data["number"], data["html_url"]


def sync(gh: GitHub, wanted: list[Issue]) -> list[Result]:
    """wanted のうち、同じ件名の Issue がないものだけ起票する。結果は wanted と同じ順。"""
    if not wanted:
        return []
    have = gh.existing()
    gh.ensure_label()
    out = []
    for issue in wanted:
        if issue.title in have:
            n, url = have[issue.title]
            out.append(Result(issue.title, n, url, False))
            continue
        n, url = gh.create(issue)
        have[issue.title] = (n, url)  # 同じ件名を 2 回起票しない
        out.append(Result(issue.title, n, url, True))
    return out
