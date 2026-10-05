"""画面共通の状態（リポジトリ、履歴、ジョブ、使用バージョン、コマンド台帳）。"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from craft_app import jobs, photocraft, releases
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


def flash(scope: str, kind: str, msg: str) -> None:
    """st.rerun() のあとに出すメッセージを預ける。"""
    st.session_state[f"flash:{scope}"] = (kind, msg)


def show_flash(scope: str) -> None:
    if item := st.session_state.pop(f"flash:{scope}", None):
        getattr(st, item[0])(item[1])
