"""コマンド台帳（requirements.md FR-08）。docs/commands.md の表を画面で編集する。"""

from __future__ import annotations

import streamlit as st

from craft_app import ledger, recipes

from . import common

COLS = {"command": "コマンド", "params": "params（例）", "purpose": "用途", "recipes": "使用レシピ", "verified": "検証日"}


def _path():
    return common.repo().root / "docs" / "commands.md"


def _rows_from(df) -> list[ledger.Row]:
    out = []
    for rec in df.to_dict("records"):
        cells = {k: ("" if rec.get(v) is None or rec.get(v) != rec.get(v) else str(rec.get(v)).strip()) for k, v in COLS.items()}
        if cells["command"]:
            out.append(ledger.Row(**cells))
    return out


def render() -> None:
    st.title("コマンド台帳")
    common.show_flash("ledger")
    st.caption("`docs/commands.md` の表を編集します。表の外の文章（注意書きや「版間の変化」）は変えません。")
    path = _path()
    led = ledger.load(path)
    reg, reg_src = common.registry()
    recs = recipes.list_recipes(common.repo().actions_dir)

    # 表示中の行（未保存の編集を含む）。ファイルが別の場所で変わったら、編集していなければ読み直す
    disk = [r.as_dict() for r in led.rows]
    if "ledger_disk" not in st.session_state or (st.session_state["ledger_disk"] != disk and st.session_state.get("ledger_rows") == st.session_state["ledger_disk"]):
        st.session_state["ledger_rows"] = disk
        st.session_state["ledger_disk"] = disk
        st.session_state["ledger_v"] = st.session_state.get("ledger_v", 0) + 1
    rows = [ledger.Row(**d) for d in st.session_state["ledger_rows"]]

    b = st.columns(4)
    if b[0].button("レシピから収集", icon=":material/playlist_add_check:", help="レシピで使っているコマンドを足し、「使用レシピ」を最新にします（手で書いた用途・検証日は変えません）"):
        got = ledger.collect(rows, recs, reg)
        st.session_state["ledger_rows"] = [r.as_dict() for r in got.rows]
        st.session_state["ledger_v"] += 1
        note = f"{len(got.added)} 件を追加" if got.added else "追加なし"
        if got.unused:
            note += f"。レシピで使われなくなった行: {', '.join(got.unused)}"
        common.flash("ledger", "info", f"収集しました（{note}）。保存すると docs/commands.md に反映されます")
        st.rerun()
    if b[1].button("成功した実行から検証日を更新", icon=":material/verified:", help="使用レシピの実行履歴（成功）から、検証日と版を更新します"):
        new, changed = ledger.with_verified(rows, ledger.successes(common.history().runs(1000)))
        st.session_state["ledger_rows"] = [r.as_dict() for r in new]
        st.session_state["ledger_v"] += 1
        common.flash("ledger", "info", f"検証日を更新しました（{len(changed)} 件）。保存すると反映されます" if changed else "更新する検証日はありませんでした")
        st.rerun()
    dirty = st.session_state["ledger_rows"] != disk
    if b[2].button("保存", type="primary", disabled=not dirty, icon=":material/save:"):
        led.rows = rows
        led.has_table = True
        ledger.save(path, led)
        st.session_state.pop("ledger_disk", None)
        common.flash("ledger", "success", f"{common.rel(path)} を保存しました（コミットして共有してください）")
        st.rerun()
    if b[3].button("変更を破棄", disabled=not dirty, icon=":material/undo:"):
        st.session_state["ledger_rows"] = disk
        st.session_state["ledger_v"] += 1
        st.rerun()
    if dirty:
        st.caption("未保存の変更があります")

    import pandas as pd

    df = pd.DataFrame([{COLS[k]: v for k, v in r.items()} for r in st.session_state["ledger_rows"]], columns=list(COLS.values()))
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, width="stretch", key=f"ledger_editor_{st.session_state['ledger_v']}",
        column_config={COLS["command"]: st.column_config.TextColumn(required=True), COLS["purpose"]: st.column_config.TextColumn(width="large")},
    )
    st.session_state["ledger_rows"] = [r.as_dict() for r in _rows_from(edited)]

    if reg is not None:
        gone = ledger.missing_in(_rows_from(edited), reg)
        if gone:
            st.warning(f"{reg_src} にないコマンドがあります（削除・改名の可能性）: {', '.join(gone)}")
    used = common.used_commands()
    unlisted = sorted(used - {r.command for r in _rows_from(edited)})
    if unlisted:
        st.info(f"レシピで使っているが台帳にないコマンド: {', '.join(unlisted)}（「レシピから収集」で足せます）")
    st.caption(f"照合元: {reg_src}")
