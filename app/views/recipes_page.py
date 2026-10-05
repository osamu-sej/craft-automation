"""レシピ管理（requirements.md FR-01）。"""

from __future__ import annotations

import streamlit as st

from craft_app import recipes

from . import common

NEW = "＋ 新規作成"


def _editor_key(name: str) -> str:
    return f"editor:{name}"


def _add_step(key: str, command: str) -> None:
    try:
        st.session_state[key] = recipes.append_step(st.session_state[key], command)
    except (ValueError, KeyError) as e:
        common.flash("recipes", "error", f"追加できません（JSON を直してから追加してください）: {e}")


def _revert(key: str, text: str) -> None:
    st.session_state[key] = text
    st.session_state[f"{key}:base"] = text


def render() -> None:
    st.title("レシピ")
    repo = common.repo()
    rs = recipes.list_recipes(repo.actions_dir)
    reg, reg_src = common.registry()
    last = common.history().last_by_recipe()

    # ウィジェットの状態は描画前にしか変えられないため、前回の操作の結果をここで反映する
    for k in st.session_state.pop("recipe_reset", []):
        st.session_state.pop(k, None)
    if "recipe_pending" in st.session_state:
        st.session_state["recipe_choice"] = st.session_state.pop("recipe_pending")
    common.show_flash("recipes")

    rows = []
    for r in rs:
        v = recipes.validate(r.text, reg)
        run = last.get(r.name)
        rows.append({
            "名前": r.name,
            "ステップ": len(v.steps),
            "tested_with": v.tested_with or "",
            "検証": "エラー" if v.errors else f"警告 {len(v.warnings)}" if v.warnings else "OK",
            "最終実行": f"{common.STATUS_JA.get(run['status'], run['status'])}（{run['tag']}）" if run else "",
            "最終実行日時": common.when(run["started_at"]) if run else "",
        })
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    st.caption(f"保存先: {common.rel(repo.actions_dir)}/<名前>.json　照合元: {reg_src}")

    names = [r.name for r in rs]
    choice = st.selectbox("編集するレシピ", [*names, NEW], key="recipe_choice")
    if choice == NEW:
        _create(repo.actions_dir, names)
        return
    recipe = next(r for r in rs if r.name == choice)
    key = _editor_key(recipe.name)
    base = f"{key}:base"  # エディタに読み込んだときのファイル内容
    changed_on_disk = st.session_state.get(base) != recipe.text
    if key not in st.session_state or (changed_on_disk and st.session_state[key] == st.session_state.get(base)):
        st.session_state[key] = st.session_state[base] = recipe.text  # 未編集なら最新のファイルを読み直す
    elif changed_on_disk:
        st.warning("編集中にファイルが別の場所で変更されました（一括実行の「検証済みにする」など）。保存すると上書きします。「変更を破棄」で読み直せます")

    left, right = st.columns([3, 2])
    with left:
        text = st.text_area("JSON", key=key, height=360, help='`[{"command": ID, "params": {…}}]` または `{"tested_with": "v…", "actions": [...]}`')
        v = recipes.validate(text, reg)
        for e in v.errors:
            st.error(e)
        for w in v.warnings:
            st.warning(w)
        if v.ok and not v.warnings:
            st.success(f"{len(v.steps)} ステップ。問題はありません")
        dirty = text != recipe.text
        b1, b2 = st.columns(2)
        if b1.button("保存", type="primary", disabled=not v.ok or not dirty, icon=":material/save:"):
            recipes.save(repo.actions_dir, recipe.name, text, overwrite=True)
            common.flash("recipes", "success", f"{recipe.path.name} を保存しました")
            st.session_state["recipe_reset"] = [key, base]
            st.rerun()
        b2.button("変更を破棄", disabled=not dirty, on_click=_revert, args=(key, recipe.text), icon=":material/undo:")
        if dirty:
            st.caption("未保存の変更があります")

    with right:
        _lookup(reg, key)

    with st.expander("複製・削除"):
        new = st.text_input("複製先の名前", key=f"dup:{recipe.name}")
        if st.button("複製", icon=":material/content_copy:"):
            try:
                recipes.save(repo.actions_dir, new, recipe.text, overwrite=False)
            except (ValueError, FileExistsError) as e:
                st.error(str(e))
            else:
                common.flash("recipes", "success", f"{new}.json を作成しました")
                st.session_state["recipe_pending"] = new
                st.rerun()
        st.divider()
        sure = st.checkbox(f"{recipe.path.name} を削除する", key=f"del:{recipe.name}")
        if st.button("削除", disabled=not sure, icon=":material/delete:"):
            recipes.delete(recipe.path)
            st.session_state["recipe_reset"] = [key, base, "recipe_choice"]
            common.flash("recipes", "success", f"{recipe.path.name} を削除しました")
            st.rerun()


def _create(actions_dir, names: list[str]) -> None:
    name = st.text_input("名前（拡張子なし）", key="new_name")
    if st.button("作成", type="primary", icon=":material/add:"):
        try:
            recipes.save(actions_dir, name, recipes.TEMPLATE, overwrite=False)
        except (ValueError, FileExistsError) as e:
            st.error(str(e))
        else:
            common.flash("recipes", "success", f"{name}.json を作成しました")
            st.session_state["recipe_pending"] = name
            st.rerun()


def _lookup(reg, key: str) -> None:
    st.markdown("**コマンドを探す**")
    if reg is None:
        st.caption("PhotoCraft を導入するとコマンド一覧から探せます")
        return
    q = st.text_input("ID・名前・メニューで検索", key="cmd_q", placeholder="例: sharpen, curves, Blur")
    if not q:
        st.caption(f"{len(reg)} 件のコマンドがあります")
        return
    ql = q.lower()
    hits = [c for c in reg.values() if ql in f"{c.id} {c.label} {c.menu}".lower()][:50]
    if not hits:
        st.caption("見つかりません")
        return
    pick = st.selectbox(f"{len(hits)} 件", [c.id for c in hits], format_func=lambda i: f"{i}　{reg[i].label}")
    c = reg[pick]
    st.caption(c.menu)
    st.code(c.params_doc or "（params の説明なし）", language=None, wrap_lines=True)
    st.button("このコマンドを末尾に追加", on_click=_add_step, args=(key, c.id), icon=":material/playlist_add:")
