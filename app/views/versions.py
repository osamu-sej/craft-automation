"""PhotoCraft のバージョン管理（requirements.md FR-02）。"""

from __future__ import annotations

import platform

import streamlit as st

from craft_app import photocraft, releases

from . import common


def render() -> None:
    st.title("バージョン")
    common.show_flash("versions")
    repo = common.repo()
    rels, source = common.release_list()
    pin = repo.pinned()
    newest = releases.latest(rels)
    inst = {i.tag: i for i in common.installed()}
    try:
        asset = photocraft.asset_for(pin or newest or "v0.0.0")
    except photocraft.UnsupportedPlatform as e:
        st.error(str(e))
        return

    c = st.columns(3)
    c[0].metric("ピン（.photocraft-version）", pin or "-")
    c[1].metric("最新リリース", newest or "-")
    c[2].metric("この PC", f"{platform.system()} {platform.machine()}")
    st.caption(f"取得する asset: `{asset.name}`（{photocraft.CHECKSUMS} で SHA256 を検証）。展開先: {common.rel(repo.bin_dir)}/<版>/")
    if pin and newest and pin != newest:
        st.info(f"ピン {pin} より新しい {newest} があります。ピンの更新は docs/upstream-tracking.md の手順（差分確認 → スモーク → 記録）で行います")

    st.subheader("リリース")
    if not rels:
        st.warning(f"リリース一覧を取得できませんでした（{source}）。下の欄にタグを直接入力して導入できます")
    else:
        st.caption(f"取得元: {source}")
        rows = [{
            "タグ": r.tag,
            "種別": "プレリリース" if r.prerelease else "正式",
            "公開日": r.published_at[:10],
            "印": " ".join(x for x, ok in [("ピン", r.tag == pin), ("最新", r.tag == newest)] if ok),
            "状態": "導入済み" if r.tag in inst else "",
        } for r in rels]
        if not any(row["公開日"] for row in rows):  # git のタグからは公開日が分からない
            for row in rows:
                del row["公開日"]
        st.dataframe(rows, hide_index=True, width="stretch")
    if st.button("一覧を再取得", icon=":material/refresh:"):
        common.release_list.clear()
        st.rerun()

    st.subheader("導入")
    candidates = [r.tag for r in rels if r.tag not in inst]
    default = next((t for t in (pin, newest) if t in candidates), candidates[0] if candidates else "")
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    if candidates:
        tag = c1.selectbox("導入する版", candidates, index=candidates.index(default) if default else 0)
    else:
        tag = c1.text_input("導入する版（タグ）", pin or "", placeholder="例: v0.2.0")
    if c2.button("導入", type="primary", disabled=not tag, icon=":material/download:"):
        bar = st.progress(0.0, text=f"{tag} を取得中…")

        def progress(done: int, total: int) -> None:
            bar.progress(min(done / total, 1.0) if total else 0.0, text=f"{tag} を取得中… {done / 1e6:.1f} / {total / 1e6:.1f} MB")

        try:
            got = releases.install(tag, repo.bin_dir, progress)
        except releases.DownloadError as e:
            bar.empty()
            st.error(str(e))
        except Exception as e:  # noqa: BLE001 - 原因をそのまま見せる（§4 可観測性）
            bar.empty()
            st.error(f"{tag} を導入できませんでした: {e}")
        else:
            bar.empty()
            common.flash("versions", "success", f"{tag} を導入しました: {common.version_of(got)}")
            st.rerun()

    st.subheader("導入済み")
    if not inst:
        st.caption("まだありません")
    for i in inst.values():
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.markdown(f"**{i.tag}**{'（ピン）' if i.tag == pin else ''}　`{common.version_of(i)}`")
            a.caption(common.rel(i.cli))
            if b.button("削除", key=f"rm:{i.tag}", icon=":material/delete:"):
                releases.uninstall(i.tag, repo.bin_dir)
                st.rerun()
