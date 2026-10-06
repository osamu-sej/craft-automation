"""実行履歴（requirements.md §4 再現性・可観測性）。"""

from __future__ import annotations

import streamlit as st

from . import common

KIND = {"batch": "一括実行", "smoke": "スモーク"}


def render() -> None:
    st.title("履歴")
    runs = common.history().runs()
    if not runs:
        st.info("まだ実行していません")
        return
    st.dataframe(
        [{
            "開始": common.when(r["started_at"]),
            "種別": KIND.get(r["kind"], r["kind"]),
            "レシピ": r["recipe"],
            "版": r["tag"],
            "状態": common.STATUS_JA.get(r["status"], r["status"]),
            "成功": r["ok"],
            "失敗": r["failed"],
            "入力": common.rel(r["in_dir"]),
            "出力": common.rel(r["out_dir"]),
        } for r in runs],
        hide_index=True, width="stretch",
    )
    pick = st.selectbox("詳細を見る", range(len(runs)), format_func=lambda k: f"{common.when(runs[k]['started_at'])}　{runs[k]['recipe']}（{runs[k]['tag']}）")
    r = runs[pick]
    st.markdown(f"**{common.STATUS_JA.get(r['status'], r['status'])}**　終了コード {r['exit_code']}　{common.when(r['started_at'])} → {common.when(r['finished_at'])}")
    st.caption("PhotoCraft")
    st.code(r["version"] or r["tag"], language=None)
    st.caption("実行コマンド")
    st.code(r["command"], language=None, wrap_lines=True)
    st.caption("レシピ内容の SHA256")
    st.code(r["recipe_hash"], language=None)
    with st.expander("ログ全文"):
        st.code(r["log"] or "", language=None)
    st.caption(f"保存先: {common.history().path}")
