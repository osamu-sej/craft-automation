"""画面共通の状態（リポジトリ、履歴、ジョブ、使用バージョン、コマンド台帳）。"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from craft_app import issues, jobs, photocraft, recipes, releases, secrets, settings, upstream
from craft_app.paths import Repo, app_data_dir, default_repo_root


# ページ（streamlit_app.py が登録する）。st.page_link の行き先に使う
PAGES: dict = {}

STATUS_JA = {"running": "実行中", "succeeded": "成功", "failed": "失敗あり", "cancelled": "キャンセル", "error": "起動エラー"}


def when(iso: str) -> str:
    """履歴の時刻（ISO 8601）を `2026-10-05 21:58` の形で出す。"""
    return iso[:16].replace("T", " ") if iso else ""


@st.cache_resource
def services() -> tuple[Repo, jobs.History, jobs.JobManager]:
    repo = Repo(default_repo_root())
    history = jobs.History(app_data_dir() / "runs.sqlite")
    return repo, history, jobs.JobManager(history)


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def app_settings() -> dict:
    return settings.load(settings_path())


def issue_repo() -> str:
    """Issue の起票先 owner/repo（設定 → origin → 空）。"""
    return app_settings()["issue_repo"] or settings.origin_slug(repo().root) or ""


def issue_client() -> tuple[issues.GitHub | None, str]:
    """起票に使うクライアント。使えないときは理由を返す（トークンの値は返さない）。"""
    slug = issue_repo()
    if not slug:
        return None, "起票先のリポジトリ（owner/repo）が未設定です"
    if (err := settings.check_slug(slug)) is not None:
        return None, err
    token, _ = secrets.get_token()
    if not token:
        return None, "GitHub トークンが未設定です"
    return issues.GitHub(slug, token), ""


def _check_and_file() -> upstream.Status:
    """本家を確認し、自動起票がオンなら未起票の更新を起票する（FR-05）。"""
    r = repo()
    status = upstream.check(r.root, r.pinned(), app_data_dir() / "upstream.git")
    if app_settings()["auto_issue"]:
        gh, why = issue_client()
        if gh is None:
            status.notes.append(f"自動起票: {why}")
        else:
            try:
                done = issues.sync(gh, issues.pending(status))
                status.notes.append(f"自動起票: {sum(x.created for x in done)} 件を起票（{gh.slug}）")
            except issues.GitHubError as e:
                status.notes.append(f"自動起票に失敗: {e}")
    return status


@st.cache_resource
def watcher() -> upstream.Watcher:
    """本家更新の確認（起動時と 24 時間ごと。FR-05）。CRAFT_UPSTREAM_AUTO=0 で自動確認を止める。"""
    return upstream.Watcher(_check_and_file, auto=os.environ.get("CRAFT_UPSTREAM_AUTO", "1") != "0")


def used_commands() -> set[str]:
    """レシピで使っているコマンド ID。"""
    out: set[str] = set()
    for r in recipes.list_recipes(repo().actions_dir):
        out |= {s.command for s in recipes.validate(r.text).steps}
    return out


def registry_for(tag: str) -> tuple[dict[str, photocraft.Command] | None, str]:
    """指定した版のコマンド台帳。導入済みならその CLI、なければスナップショット。"""
    inst = {i.tag: i for i in installed()}
    if tag in inst:
        try:
            return _registry(str(inst[tag].cli), inst[tag].cli.stat().st_mtime), f"{tag} の commands --json"
        except Exception:  # noqa: BLE001 - スナップショットで代用する
            pass
    snap = repo().snapshot_dir / tag / "generated" / "commands.json"
    if snap.is_file():
        return photocraft.parse_registry(snap.read_text(encoding="utf-8")), f"スナップショット {tag}"
    return None, ""


def repo() -> Repo:
    return services()[0]


def history() -> jobs.History:
    return services()[1]


def manager() -> jobs.JobManager:
    return services()[2]


def rel(p: Path | str) -> str:
    """リポジトリ内ならリポジトリ基準の相対パスで表示する。"""
    p = Path(p)
    try:
        return p.resolve().relative_to(repo().root.resolve()).as_posix()
    except ValueError:
        return str(p)


@st.cache_data(ttl=600, show_spinner="本家のリリース一覧を取得中…")
def release_list() -> tuple[list[releases.Release], str]:
    return releases.list_releases()


@st.cache_data(show_spinner=False)
def _version(cli: str, mtime: float) -> str:
    try:
        return photocraft.cli_version(Path(cli))
    except Exception as e:  # noqa: BLE001 - 画面に出す
        return f"（--version 失敗: {e}）"


def version_of(inst: releases.Installed) -> str:
    return _version(str(inst.cli), inst.cli.stat().st_mtime)


@st.cache_data(show_spinner="コマンド台帳を読み込み中…")
def _registry(cli: str, mtime: float) -> dict[str, photocraft.Command]:
    return photocraft.load_registry(Path(cli))


def install_with_progress(tag: str) -> releases.Installed | None:
    """tag を導入する。進捗を出し、失敗したら理由（URL・HTTP ステータス）を出して None を返す。"""
    bar = st.progress(0.0, text=f"{tag} を取得中…")

    def progress(done: int, total: int) -> None:
        bar.progress(min(done / total, 1.0) if total else 0.0, text=f"{tag} を取得中… {done / 1e6:.1f} / {total / 1e6:.1f} MB")

    try:
        got = releases.install(tag, repo().bin_dir, progress)
    except releases.DownloadError as e:
        st.error(str(e))
        return None
    except Exception as e:  # noqa: BLE001 - 原因をそのまま見せる（§4 可観測性）
        st.error(f"{tag} を導入できませんでした: {e}")
        return None
    finally:
        bar.empty()
    return got


def installed() -> list[releases.Installed]:
    return releases.installed(repo().bin_dir)


def current() -> releases.Installed | None:
    """サイドバーで選んだ使用バージョン。"""
    inst = {i.tag: i for i in installed()}
    tag = st.session_state.get("tag")
    if tag in inst:
        return inst[tag]
    pin = repo().pinned()
    if pin in inst:
        return inst[pin]
    return next(iter(inst.values()), None)


def registry() -> tuple[dict[str, photocraft.Command] | None, str]:
    """コマンド名・params の照合元。使用バージョンの `commands --json`、なければピン版のスナップショット。"""
    inst = current()
    if inst is not None:
        try:
            return _registry(str(inst.cli), inst.cli.stat().st_mtime), f"{inst.tag} の commands --json"
        except Exception as e:  # noqa: BLE001
            st.warning(f"コマンド台帳を読めませんでした: {e}")
    pin = repo().pinned()
    snap = repo().snapshot_dir / (pin or "") / "generated" / "commands.json"
    if pin and snap.is_file():
        return photocraft.parse_registry(snap.read_text(encoding="utf-8")), f"スナップショット {pin}"
    return None, "なし（コマンド名は照合しません）"


def sidebar() -> None:
    r = repo()
    st.sidebar.caption("作業ディレクトリ")
    st.sidebar.code(str(r.root), language=None)
    inst = installed()
    pin = r.pinned()
    if not inst:
        st.sidebar.warning("PhotoCraft が未導入です。「バージョン」から導入してください。")
        return
    tags = [i.tag for i in inst]
    if st.session_state.get("tag") not in tags:  # 削除された版を選んだままにしない
        st.session_state.pop("tag", None)
    cur = current()
    st.sidebar.selectbox(
        "使用バージョン",
        tags,
        index=tags.index(cur.tag) if cur else 0,
        format_func=lambda t: f"{t}（ピン）" if t == pin else t,
        key="tag",
    )
    if pin and pin not in tags:
        st.sidebar.info(f"ピン {pin} は未導入です")


def upstream_badge() -> None:
    """サイドバーに本家更新の確認待ち件数を出す（OS 通知の代わり。ADR 0001）。"""
    w = watcher()
    if w.status is None:
        st.sidebar.caption("本家の更新: 確認中…" if w.running else "本家の更新: 未確認")
        return
    n = upstream.apply_records(w.status, repo().root).pending
    if n and "upstream" in PAGES:
        st.sidebar.page_link(PAGES["upstream"], label=f"本家の更新を確認（{n} 件）", icon=":material/notifications_active:")
    else:
        st.sidebar.caption(f"本家の更新: 確認待ちなし（{when(w.status.checked_at)}）")


def flash(scope: str, kind: str, msg: str) -> None:
    """st.rerun() のあとに出すメッセージを預ける。"""
    st.session_state[f"flash:{scope}"] = (kind, msg)


def show_flash(scope: str) -> None:
    if item := st.session_state.pop(f"flash:{scope}", None):
        getattr(st, item[0])(item[1])
