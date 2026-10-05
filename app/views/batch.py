"""一括実行（requirements.md FR-03）。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st

from craft_app import photocraft, recipes

from . import common

PREVIEWABLE = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"}
STATUS = {
    "running": ("実行中", "blue"),
    "succeeded": ("成功", "green"),
    "failed": ("失敗あり", "red"),
    "cancelled": ("キャンセル", "orange"),
    "error": ("起動エラー", "red"),
}


def render() -> None:
    st.title("一括実行")
    common.show_flash("batch")
    repo = common.repo()
    inst = common.current()
    rs = recipes.list_recipes(repo.actions_dir)
    if inst is None:
        st.warning("PhotoCraft が未導入です。「バージョン」ページで導入してください。")
        if "versions" in common.PAGES:
            st.page_link(common.PAGES["versions"], label="バージョンへ", icon=":material/download:")
        return
    if not rs:
        st.info("actions/ にレシピがありません。「レシピ」ページで作成してください。")
        return

    c1, c2 = st.columns(2)
    name = c1.selectbox("レシピ", [r.name for r in rs], key="batch_recipe")
    recipe = next(r for r in rs if r.name == name)
    c2.text_input("使用バージョン", f"{inst.tag} — {common.version_of(inst)}", disabled=True, help="サイドバーで切り替えます")
    in_text = c1.text_input("入力フォルダ", "samples/in", key="batch_in", help="リポジトリ基準の相対パス、または絶対パス。フォルダ直下の画像だけを処理します（サブフォルダは対象外）")
    out_text = c2.text_input("出力フォルダ", "samples/out", key="batch_out", help="なければ作成します")
    c3, c4 = st.columns(2)
    fmt = c3.selectbox("出力形式", photocraft.OUTPUT_FORMATS, format_func=lambda f: f or "入力と同じ", key="batch_fmt")
    quality = c4.slider("JPEG 品質", 1, 100, 90, key="batch_quality") if fmt == "jpg" else None

    in_dir, out_dir = repo.resolve(in_text), repo.resolve(out_text)
    inputs = photocraft.list_inputs(in_dir)
    reg, _ = common.registry()
    v = recipes.validate(recipe.text, reg)
    blockers = list(v.errors)
    if not in_dir.is_dir():
        blockers.append(f"入力フォルダがありません: {in_dir}")
    elif not inputs:
        blockers.append("入力フォルダに処理できる画像がありません（batch は0件でも成功扱いで終わります）")
    if in_dir.resolve() == out_dir.resolve():
        blockers.append("入力と出力が同じフォルダです。元画像が上書きされるため実行できません")

    with st.container(border=True):
        st.markdown(f"**{len(inputs)} 件**を処理します（{common.rel(in_dir)} → {common.rel(out_dir)}）")
        names = Counter(photocraft.output_name(p, fmt) for p in inputs)
        dup = [n for n, k in names.items() if k > 1]
        if dup:
            st.warning(f"出力名が重なり、後の画像で上書きされます: {', '.join(dup[:5])}{' ほか' if len(dup) > 5 else ''}")
        existing = [n for n in names if (out_dir / n).exists()]
        if existing:
            st.info(f"出力フォルダの既存ファイル {len(existing)} 件を上書きします")
        for w in v.warnings:
            st.warning(w)
        if v.tested_with and v.tested_with != inst.tag:
            st.info(f"このレシピの検証済み版は {v.tested_with} です（使用バージョンは {inst.tag}）")
        for b in blockers:
            st.error(b)

    job_id = st.session_state.get("batch_job")
    job = common.manager().jobs.get(job_id) if job_id else None
    running = job is not None and not job.done
    if st.button("実行", type="primary", disabled=bool(blockers) or running, icon=":material/play_arrow:"):
        job = common.manager().start_batch(
            inst.cli, inst.tag, common.version_of(inst), recipe.path, recipe.hash, in_dir, out_dir, fmt, quality
        )
        st.session_state["batch_job"] = job.id
        st.rerun()

    if job is not None:
        st.divider()
        if not job.done:
            _progress(job.id)
        else:
            _result(job)


@st.fragment(run_every=1.0)
def _progress(job_id: str) -> None:
    job = common.manager().jobs[job_id]
    if job.done:
        st.rerun()
    done = len(job.ok) + len(job.failed)
    st.progress(min(done / job.expected, 1.0) if job.expected else 0.0, text=f"{done} / {job.expected} 件（成功 {len(job.ok)}・失敗 {len(job.failed)}）")
    if st.button("キャンセル", icon=":material/stop:", disabled=job.cancel_requested):
        common.manager().cancel(job_id)
    st.code("\n".join(line for _, line in job.log[-15:]) or "（出力待ち）", language=None)


def _result(job) -> None:
    label, color = STATUS[job.status]
    st.subheader(f":{color}[{label}]　{job.recipe}（{job.tag}）")
    c = st.columns(4)
    c[0].metric("成功", len(job.ok))
    c[1].metric("失敗", len(job.failed))
    c[2].metric("警告", len(job.warnings))
    c[3].metric("終了コード", "-" if job.exit_code is None else job.exit_code)
    st.caption("実行コマンド")
    st.code(job.command, language=None, wrap_lines=True)
    if job.failed:
        st.dataframe([{"入力": common.rel(i), "理由": why} for i, why in job.failed], hide_index=True, width="stretch")
    if job.warnings:
        with st.expander(f"警告 {len(job.warnings)} 件"):
            for w, n in Counter(job.warnings).most_common():
                st.write(f"- {w}（{n} 件）")
    with st.expander("ログ全文"):
        st.code(job.log_text(), language=None)

    recipe_path = common.repo().actions_dir / f"{job.recipe}.json"
    if job.status == "succeeded" and recipe_path.is_file():
        tested = recipes.validate(recipe_path.read_text(encoding="utf-8")).tested_with
        if tested != job.tag and st.button(f"このレシピを {job.tag} で検証済みにする（tested_with）", icon=":material/verified:"):
            recipes.mark_tested(recipe_path, job.tag)
            common.flash("batch", "success", f"{recipe_path.name} の tested_with を {job.tag} にしました")
            st.rerun()

    _gallery(job)


def _gallery(job) -> None:
    pairs = [(Path(i), Path(o)) for i, o in job.ok]
    if not pairs:
        return
    st.subheader("出力")
    shown = [(i, o) for i, o in pairs if o.suffix[1:].lower() in PREVIEWABLE and o.is_file()]
    if not shown:
        st.caption("この形式はプレビューできません")
        return
    cols = st.columns(4)
    for k, (_, o) in enumerate(shown[:12]):
        cols[k % 4].image(str(o), caption=o.name, width="stretch")
    if len(shown) > 12:
        st.caption(f"ほか {len(shown) - 12} 件（{common.rel(job.out_dir)}）")
    st.subheader("入出力の比較")
    pick = st.selectbox("ファイル", range(len(shown)), format_func=lambda k: shown[k][0].name, key=f"cmp_{job.id}")
    i, o = shown[pick]
    a, b = st.columns(2)
    if i.suffix[1:].lower() in PREVIEWABLE and i.is_file():
        a.image(str(i), caption=f"入力: {i.name}", width="stretch")
    else:
        a.caption(f"入力 {i.name} はプレビューできません")
    b.image(str(o), caption=f"出力: {o.name}", width="stretch")
