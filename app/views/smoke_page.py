"""スモークテスト（requirements.md FR-04）。"""

from __future__ import annotations

import streamlit as st

from craft_app import issues, photocraft, recipes, releases, smoke

from . import common

BANNER = {
    smoke.BREAKING: ("error", "破壊的変更があります。ピン版で成功したレシピが最新版で失敗しました。docs/upstream-tracking.md の手順で、レシピと docs/commands.md を直してください"),
    "互換（ピンを更新してよい）": ("success", "互換です。すべてのレシピが両方の版で成功しました。ピンを更新してよい状態です"),
    "成功（ピンが最新）": ("success", "ピンが最新です。すべてのレシピが成功しました"),
}


def render() -> None:
    st.title("スモークテスト")
    common.show_flash("smoke")
    st.caption("全レシピを samples/smoke/in に、ピン版と最新版の両方で適用して比べます（scripts/smoke.sh・smoke.yml と同じ判定）。")
    repo = common.repo()
    pin = repo.pinned()
    rels, _ = common.release_list()
    newest = releases.latest(rels)
    inst = {i.tag: i for i in common.installed()}

    c = st.columns(2)
    for col, label, tag in [(c[0], "ピン", pin), (c[1], "最新", newest)]:
        col.metric(label, tag or "-")
        col.caption("導入済み" if tag in inst else "未導入")

    missing = [t for t in dict.fromkeys([pin, newest]) if t and t not in inst]
    if missing:
        st.warning(f"未導入の版があります: {', '.join(missing)}")
        if st.button("未導入の版を導入", icon=":material/download:"):
            if all(common.install_with_progress(t) is not None for t in missing):
                common.flash("smoke", "success", f"{', '.join(missing)} を導入しました")
                st.rerun()

    rs = recipes.list_recipes(repo.actions_dir)
    inputs = photocraft.list_inputs(repo.root / "samples" / "smoke" / "in")
    blockers = []
    if not pin:
        blockers.append(".photocraft-version（ピン）がありません")
    if missing:
        blockers.append("ピン版と最新版を導入してから実行してください")
    if not rs:
        blockers.append("actions/ にレシピがありません")
    if not inputs:
        blockers.append("samples/smoke/in に入力画像がありません")
    for b in blockers:
        st.error(b)
    if not blockers:
        st.markdown(f"**{len(rs)} レシピ × {len({pin, newest} - {None})} 版**（入力 {len(inputs)} 件）")

    run: smoke.SmokeRun | None = st.session_state.get("smoke_run")
    running = run is not None and not run.verdict
    if st.button("スモークテストを実行", type="primary", disabled=bool(blockers) or running, icon=":material/science:"):
        versions = {t: common.version_of(inst[t]) for t in {pin, newest} if t in inst}
        st.session_state["smoke_run"] = smoke.start(common.manager(), repo, inst[pin], inst.get(newest), versions)
        st.rerun()

    if run is not None:
        st.divider()
        show_run()

    past = common.history().smokes()
    if past:
        st.subheader("これまでの結果")
        st.dataframe(
            [{"開始": common.when(r["started_at"]), "ピン": r["pinned"], "最新": r["latest"] or "（ピンと同じ）", "判定": r["verdict"]} for r in past],
            hide_index=True, width="stretch",
        )
    st.caption("CLI は params を検証しないため、成功しても params が効いているとは限りません。params のキー名の変更は「本家の更新」のコマンド台帳の差分で確認してください。")


def show_run() -> None:
    """session_state の直近のスモークテストを、進行中なら進捗、終わっていれば結果で表示する。"""
    run: smoke.SmokeRun | None = st.session_state.get("smoke_run")
    if run is None:
        return
    if not run.verdict:
        _live()
    else:
        _result(run)


@st.fragment(run_every=1.0)
def _live() -> None:
    run: smoke.SmokeRun = st.session_state["smoke_run"]
    if run.verdict:
        st.rerun()
    mgr = common.manager()
    jobs = [mgr.jobs[j] for j in run.jobs.values()]
    done = sum(j.done for j in jobs)
    st.progress(done / len(jobs) if jobs else 1.0, text=f"{done} / {len(jobs)} 件")
    st.dataframe(run.table(mgr), hide_index=True, width="stretch")


def _result(run: smoke.SmokeRun) -> None:
    kind, msg = BANNER.get(run.verdict, ("warning", f"{run.verdict}: 失敗したレシピがあります。ログを確認してください"))
    getattr(st, kind)(msg)
    mgr = common.manager()
    st.dataframe(run.table(mgr), hide_index=True, width="stretch")
    failed = [(t, r) for (t, r), j in run.jobs.items() if not smoke.job_ok(mgr.jobs[j])]
    for t, r in failed:
        job = mgr.jobs[run.jobs[(t, r)]]
        with st.expander(f"{r}（{t}）のログ"):
            st.code(job.command, language=None, wrap_lines=True)
            st.code(job.log_text() or "（出力なし）", language=None)
    st.caption(f"出力: {common.rel(common.repo().root / 'out' / 'smoke')}/<版>/<レシピ>")
    if run.verdict == smoke.BREAKING and run.latest:
        gh, why = common.issue_client()
        issue = issues.smoke_issue(run.latest.tag, run.table(mgr))
        if st.button("Issue を起票", disabled=gh is None, help=why or issue.title, icon=":material/bug_report:"):
            try:
                (res,) = issues.sync(gh, [issue])
            except issues.GitHubError as e:
                st.error(str(e))
            else:
                common.flash("smoke", "success", f"[#{res.number}]({res.url}) {'を起票しました' if res.created else 'は起票済みです'}")
                st.rerun()
