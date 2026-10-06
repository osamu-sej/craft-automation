"""本家更新ダッシュボード（requirements.md FR-05）。upstream-watch.yml の Issue の代わりに画面で確認する。"""

from __future__ import annotations

import streamlit as st

from craft_app import photocraft, upstream

from . import common


def render() -> None:
    st.title("本家の更新")
    common.show_flash("upstream")
    repo = common.repo()
    w = common.watcher()
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    if c2.button("今すぐ確認", icon=":material/refresh:", disabled=w.running):
        with st.spinner("本家を確認中…"):
            w.refresh()
        st.rerun()
    if w.error:
        st.warning(f"前回の確認に失敗しました: {w.error}")
    s = w.status
    if s is None:
        c1.caption("確認中です。しばらくしてから開き直すか「今すぐ確認」を押してください" if w.running else "まだ確認していません")
        return
    s = upstream.apply_records(s, repo.root)
    c1.caption(f"最終確認 {common.when(s.checked_at)}（起動時と 24 時間ごとに自動で確認）。" + " / ".join(s.notes))

    _releases(s, repo.pinned())
    _watched(s, repo.root)
    _registry(s, repo.pinned())


def _releases(s: upstream.Status, pin: str | None) -> None:
    st.subheader("リリース")
    if pin != s.pinned:
        st.info(f"確認後にピンが {s.pinned} から {pin} に変わりました。「今すぐ確認」で更新してください")
    c = st.columns(3)
    c[0].metric("ピン", s.pinned or "-")
    c[1].metric("最新", s.latest or "-")
    c[2].metric("差分のコミット数", "-" if s.commits is None else s.commits)
    if s.newer:
        st.warning(f"ピンより新しいリリースがあります: {', '.join(s.newer)}")
        links = [f"[差分（{s.pinned}…{s.latest}）]({s.compare_url})"]
        links += [f"[{t} のリリース](https://github.com/{photocraft.UPSTREAM}/releases/tag/{t})" for t in s.newer]
        st.markdown("　".join(links))
        st.caption("対応手順: スモークテスト（latest）を確認 → 差分と control-protocol を確認 → レシピ・docs/commands.md を修正 → ピン更新と docs/upgrade-log.md への記録（docs/upstream-tracking.md）")
    elif s.latest:
        st.success("ピンは最新です")


def _watched(s: upstream.Status, root) -> None:
    st.subheader("監視対象ファイル")
    st.caption(".upstream/watched-paths.txt の各ファイルを本家で最後に変えたコミットと、確認済みとして記録した SHA（.upstream/<key>.sha）を比べます。")
    if not s.watched:
        st.caption("監視対象がありません")
        return
    for wt in s.watched:
        with st.container(border=True):
            a, b = st.columns([4, 1], vertical_alignment="center")
            icon = {"確認済み": ":green[確認済み]", "変更あり": ":orange[変更あり]", "未記録": ":orange[未記録]", "取得失敗": ":red[取得失敗]"}[wt.status]
            latest = f"`{wt.latest.sha[:7]}`（{common.when(wt.latest.date)}）" if wt.latest else "-"
            recorded = f"`{wt.recorded[:7]}`" if wt.recorded else "なし"
            a.markdown(f"**{wt.path}**　{icon}  \n本家の最新 {latest}　記録 {recorded}　[履歴]({upstream.commits_url(wt.path)})")
            if wt.pending and wt.latest and b.button("確認済みにする", key=f"ack:{wt.path}", icon=":material/done:"):
                f = upstream.record_sha(root, wt.path, wt.latest.sha)
                common.flash("upstream", "success", f"{wt.path} を確認済みにしました（{common.rel(f)} に記録。コミットして共有してください）")
                st.rerun()


def _registry(s: upstream.Status, pin: str | None) -> None:
    st.subheader("コマンド台帳の差分（ピン → 最新）")
    if not pin or not s.latest or pin == s.latest:
        st.caption("比べる版がありません（ピンが最新）")
        return
    old, old_src = common.registry_for(pin)
    new, new_src = common.registry_for(s.latest)
    if old is None or new is None:
        st.info(f"{s.latest if new is None else pin} を導入すると比べられます（「バージョン」ページ）")
        return
    d = upstream.diff_registry(old, new)
    used = common.used_commands()
    st.caption(f"{old_src} と {new_src} を比べています。CLI は params を検証しないため、キー名の変更はスモークテストでは見つかりません。")
    c = st.columns(3)
    c[0].metric("追加", len(d.added))
    c[1].metric("削除", len(d.removed))
    c[2].metric("params の書式変更", len(d.changed))
    hit = d.touches(used)
    if hit:
        st.error(f"レシピで使っているコマンドが削除・変更されています: {', '.join(hit)}")
        for cid in hit:
            if cid in d.removed:
                st.markdown(f"- `{cid}`: 最新版にありません")
                continue
            o, n = next((o, n) for k, o, n in d.changed if k == cid)
            gone = upstream.removed_keys(o, n)
            st.markdown(f"- `{cid}`: 書式が変わりました（" + (f"消えたキー: {', '.join(gone)}" if gone else "消えたキーはなし") + "）")
            st.code(f"- {o}\n+ {n}", language="diff", wrap_lines=True)
    elif used:
        st.success(f"レシピで使っているコマンド（{len(used)} 件）に削除・書式変更はありません")
    with st.expander("すべての差分"):
        if d.added:
            st.markdown("**追加**: " + ", ".join(f"`{c}`" for c in d.added))
        if d.removed:
            st.markdown("**削除**: " + ", ".join(f"`{c}`" for c in d.removed))
        if d.changed:
            st.dataframe([{"コマンド": k, "ピン": o, "最新": n} for k, o, n in d.changed], hide_index=True, width="stretch")
