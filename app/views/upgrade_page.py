"""アップグレード手順ウィザード（requirements.md FR-06）。ピンの更新を、4 手順をすべて終えたときだけ許す。"""

from __future__ import annotations

import streamlit as st

from craft_app import photocraft, recipes, releases, smoke, snapshot, upgrade, upstream

from . import common, smoke_page, upstream_page


def _mark(ok: bool) -> str:
    return ":green[✅]" if ok else ":gray[⬜]"


def render() -> None:
    st.title("ピン更新")
    common.show_flash("upgrade")
    repo = common.repo()
    pin = repo.pinned()
    st.caption("docs/upstream-tracking.md の「更新時の手順」を、飛ばせない形で進めます。4 つの手順がすべて終わったときだけ、ピン（.photocraft-version）を更新します。")
    if not pin:
        st.error(".photocraft-version（ピン）がありません")
        return
    rels, _ = common.release_list()
    newer = []
    keys = [r.tag for r in rels]
    if pin in keys:
        newer = keys[: keys.index(pin)]
    if not newer:
        st.success(f"ピン {pin} は最新です。更新するものはありません")
        return
    target = st.selectbox("更新先の版", newer, key="upg_target", help="ピンより新しいリリース。通常は最新を選びます")
    inst = {i.tag: i for i in common.installed()}
    w = common.watcher()
    watched = upstream.apply_records(w.status, repo.root).watched if w.status is not None else None

    reviewed_key, step3_key = f"upg_reviewed:{pin}:{target}", f"upg_step3:{pin}:{target}"
    recs = recipes.list_recipes(repo.actions_dir)
    rhash = recipes.collection_hash(recs)
    row = common.history().latest_smoke(pin, target)
    g = upgrade.evaluate(pin, target, reviewed=st.session_state.get(reviewed_key, False), step3_done=st.session_state.get(step3_key, False),
                         watched=watched, smoke_row=row, recipes_hash=rhash)

    # ① 差分確認
    with st.container(border=True):
        st.subheader(f"{_mark(g.step1)} ① 差分を確認する")
        st.markdown(f"[差分（{pin}…{target}）]({upstream.compare_url(pin, target)})　[{target} のリリース](https://github.com/{photocraft.UPSTREAM}/releases/tag/{target})")
        _step1(w, watched, repo.root)
        st.checkbox("差分・リリース・control-protocol などの変更を読んだ", key=reviewed_key)

    # ② スモーク
    with st.container(border=True):
        st.subheader(f"{_mark(g.smoke_ok)} ② スモークテスト（{pin} → {target}）")
        _step2(pin, target, inst, g, repo)

    # ③ 修正の確認
    with st.container(border=True):
        st.subheader(f"{_mark(g.step3_done)} ③ レシピと docs/commands.md を見直す")
        upstream_page.registry_diff(pin, target)
        c = st.columns(2)
        if "recipes" in common.PAGES:
            c[0].page_link(common.PAGES["recipes"], label="レシピを直す", icon=":material/receipt_long:")
        if "ledger" in common.PAGES:
            c[1].page_link(common.PAGES["ledger"], label="コマンド台帳を直す", icon=":material/menu_book:")
        st.caption("レシピを直したら、② のスモークテストをやり直します（直した内容に対する結果だけが有効です）。")
        st.checkbox("見直しを終えた（影響がなかった場合を含む）", key=step3_key)

    # ④ 記録
    with st.container(border=True):
        st.subheader(f"{_mark(False)} ④ ピンを更新して記録する")
        _step4(g, repo, inst, target)


def _step1(w, watched, root) -> None:
    if watched is None:
        st.warning("本家をまだ確認していません。")
        if st.button("本家を確認", icon=":material/refresh:", key="upg_check"):
            with st.spinner("本家を確認中…"):
                w.refresh()
            st.rerun()
        return
    rows = [x for x in watched if x.pending or x.latest is None]
    if not rows:
        st.success("監視対象ファイルは、すべて確認済みです")
        return
    st.warning(f"確認済みにしていない監視対象が {len(rows)} 件あります。内容を読んだら確認済みにしてください。")
    for x in rows:
        link = f"[{x.path}]({upstream.commits_url(x.path)})"
        st.markdown(f"- {link}：{x.status}" + (f"（本家の最新 `{x.latest.sha[:7]}`）" if x.latest else ""))
    ok = [x for x in rows if x.latest is not None]
    if ok and st.button(f"すべて確認済みにする（{len(ok)} 件）", icon=":material/done_all:", key="upg_ack"):
        for x in ok:
            upstream.record_sha(root, x.path, x.latest.sha)
        common.flash("upgrade", "success", f"{len(ok)} 件を確認済みにしました（.upstream/ に記録。コミットして共有してください）")
        st.rerun()
    if len(ok) < len(rows):
        st.caption("取得できなかった監視対象があります。「本家の更新」ページの「今すぐ確認」でもう一度確認してください。")


def _step2(pin: str, target: str, inst: dict, g: upgrade.Gates, repo) -> None:
    missing = [t for t in (pin, target) if t not in inst]
    if missing:
        st.warning(f"未導入の版があります: {', '.join(missing)}")
        if st.button("未導入の版を導入", icon=":material/download:", key="upg_install"):
            if all(common.install_with_progress(t) is not None for t in missing):
                common.flash("upgrade", "success", f"{', '.join(missing)} を導入しました")
                st.rerun()
        return
    run = st.session_state.get("smoke_run")
    running = run is not None and not run.verdict
    if st.button("スモークテストを実行", type="primary", disabled=running, icon=":material/science:", key="upg_smoke"):
        versions = {t: common.version_of(inst[t]) for t in (pin, target)}
        st.session_state["smoke_run"] = smoke.start(common.manager(), repo, inst[pin], inst[target], versions)
        st.rerun()
    run = st.session_state.get("smoke_run")
    if run is not None and run.tags == [pin, target]:
        smoke_page.show_run()
    elif g.smoke_ok:
        st.success("過去の結果: 互換。今のレシピに対する結果です")
    else:
        st.info(g.smoke_reason)
    if run is not None and run.tags == [pin, target] and run.verdict and not g.smoke_ok:
        st.warning(g.smoke_reason)


def _step4(g: upgrade.Gates, repo, inst: dict, target: str) -> None:
    if not g.ready:
        for b in g.blockers():
            st.markdown(f"- :red[未完了] {b}")
    result = st.text_input("結果（upgrade-log.md の「結果」）", f"smoke 両版成功。{g.pinned} → {target} は互換", key=f"upg_result:{target}")
    fix = st.text_input("修正内容（upgrade-log.md の「修正内容」）", "なし", key=f"upg_fix:{target}", help="直したレシピ・台帳、本家の破壊的変更への対応など")
    mark = st.checkbox(f"全レシピの tested_with を {target} にする", value=True, key=f"upg_mark:{target}")
    snap = st.checkbox(f"docs/upstream-snapshot/{target}/ を作り直す（本家の資料を {target} に揃える）", value=True, key=f"upg_snap:{target}")
    if st.button(f"ピンを {g.pinned} → {target} に更新", type="primary", disabled=not g.ready, icon=":material/upgrade:", key="upg_apply"):
        make = None
        if snap and target not in inst:
            st.error(f"{target} が導入されていません。「バージョン」ページで導入してから、もう一度実行してください")
            return
        if snap:
            cli = inst[target].cli
            make = lambda: snapshot.create(target, cli, repo.snapshot_dir)  # noqa: E731
        try:
            with st.spinner("更新しています…（スナップショットの取得に少しかかります）"):
                done = upgrade.apply(repo, g, result=result, fix=fix, mark_tested=mark, make_snapshot=make)
        except upgrade.GateError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001 - 原因をそのまま見せる。ピンは変わっていない
            st.error(f"更新できませんでした（ピンは {g.pinned} のままです）: {e}")
        else:
            common.flash("upgrade", "success", f"ピンを {target} に更新しました。変更したファイル:\n\n" + "\n".join(f"- `{c}`" for c in done.changed)
                         + "\n\nコミットして共有してください。GitHub に対応する Issue があれば閉じます。")
            st.rerun()
    st.caption("更新するファイル: .photocraft-version、docs/upgrade-log.md" + ("、actions/*.json" if mark else "") + (f"、docs/upstream-snapshot/{target}/" if snap else ""))
