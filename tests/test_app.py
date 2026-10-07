"""画面のテスト（streamlit.testing の AppTest。モック CLI と一時リポジトリで動かす）。"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from craft_app import photocraft, releases, upstream
from conftest import write_mock_cli

HERE = Path(__file__).resolve().parent
TAG = "v9.9.9"


@pytest.fixture
def repo(tmp_path, repo_root, monkeypatch):
    root = tmp_path / "repo"
    for d in ["actions", "samples/smoke/in", "docs/upstream-snapshot"]:
        shutil.copytree(repo_root / d, root / d)
    shutil.copy(repo_root / ".photocraft-version", root / ".photocraft-version")
    # この OS で直接起動できるモック CLI を「導入済みの版」として置く
    exe = write_mock_cli(root / ".bin" / TAG / "mock" / "photocraft-cli").name
    monkeypatch.setattr(photocraft, "asset_candidates", lambda tag, *a: [photocraft.Asset("mock.zip", f"mock/{exe}", "zip")])
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v10.0.0", False, "2026-10-05T00:00:00Z"), releases.Release(TAG, False)], "テスト"))
    monkeypatch.setenv("CRAFT_UPSTREAM_AUTO", "0")  # テスト中に本家へ自動で問い合わせない
    monkeypatch.setenv("CRAFT_REPO", str(root))
    monkeypatch.setenv("CRAFT_APP_DATA", str(tmp_path / "data"))
    st.cache_resource.clear()
    st.cache_data.clear()
    yield root
    st.cache_resource.clear()
    st.cache_data.clear()


def _page(render: str) -> AppTest:
    script = f"""
from views import common, {render.split('.')[0]}
common.sidebar()
{render}()
"""
    at = AppTest.from_string(script, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_versions_page(repo):
    at = _page("versions.render")
    assert at.metric[0].value == "v0.2.0"  # ピン
    assert at.metric[1].value == "v10.0.0"  # 最新
    assert any("より新しい v10.0.0" in i.value for i in at.info)
    assert at.sidebar.selectbox[0].value == TAG  # サイドバーの使用バージョン
    assert at.selectbox[0].value == "v10.0.0"  # 未導入の最新を導入候補にする


def test_recipes_page_validates_before_save(repo):
    at = _page("recipes_page.render")
    assert at.dataframe[0].value["名前"].tolist() == ["grade"]
    editor = at.text_area[0]
    assert '"tested_with": "v0.2.0"' in editor.value
    editor.input('[{"command": "a",}]').run()
    assert any("構文エラー" in e.value for e in at.error)
    save = next(b for b in at.button if b.label == "保存")
    assert save.disabled  # 不正 JSON は保存できない（受け入れ基準 1）
    at.text_area[0].input('[{"command": "no.such.command"}]').run()
    assert any("未知のコマンド" in w.value for w in at.warning)  # 未知コマンドは警告
    next(b for b in at.button if b.label == "保存").click().run()
    assert (repo / "actions/grade.json").read_text(encoding="utf-8").strip() == '[{"command": "no.such.command"}]'


def test_recipes_page_create_and_lookup(repo):
    at = _page("recipes_page.render")
    at.selectbox(key="recipe_choice").select("＋ 新規作成").run()
    at.text_input(key="new_name").input("tone").run()
    next(b for b in at.button if b.label == "作成").click().run()
    assert not at.exception
    assert (repo / "actions/tone.json").is_file()
    assert at.selectbox(key="recipe_choice").value == "tone"
    at.text_input(key="cmd_q").input("invert").run()
    pick = next(s for s in at.selectbox if s.label.endswith("件"))
    pick.select("image.adjustments.invert").run()
    next(b for b in at.button if b.label == "このコマンドを末尾に追加").click().run()
    assert '"command": "image.adjustments.invert"' in at.text_area[0].value


def test_batch_page_runs_and_records(repo):
    at = _page("batch.render")
    at.text_input(key="batch_in").input("samples/smoke/in").run()
    assert any("1 件" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "実行").click().run()
    from views import common

    job = common.manager().jobs[at.session_state["batch_job"]]
    end = time.time() + 20
    while not job.done and time.time() < end:
        time.sleep(0.1)
    assert job.status == "succeeded", job.log_text()
    at.run()
    assert not at.exception
    assert any("成功" in s.value for s in at.subheader)
    assert (repo / "samples/out/smoke.png").is_file()
    assert common.history().runs()[0]["recipe"] == "grade"


def test_batch_page_blocks_same_folder(repo):
    at = _page("batch.render")
    at.text_input(key="batch_in").input("samples/smoke/in").run()
    at.text_input(key="batch_out").input("samples/smoke/in").run()
    assert any("同じフォルダ" in e.value for e in at.error)
    assert next(b for b in at.button if b.label == "実行").disabled


@pytest.mark.parametrize("tag,expect", [(TAG, "「失敗」になります"), ("v0.2.0", "後の画像で上書きされます")])
def test_batch_page_collision_warning_follows_the_version(repo, tag, expect):
    """同名の出力が重なったときの挙動は版で違う（v0.3.0 から後の画像は失敗）。警告は使用版に合わせる。"""
    shutil.copy(repo / "samples/smoke/in/smoke.png", repo / "samples/smoke/in/smoke.jpg")
    write_mock_cli(repo / ".bin" / "v0.2.0" / "mock" / "photocraft-cli")
    at = _page("batch.render")
    at.sidebar.selectbox[0].select(tag).run()
    at.text_input(key="batch_in").input("samples/smoke/in").run()
    at.selectbox(key="batch_fmt").select("png").run()
    msgs = [w.value for w in at.warning if "出力名が重なり" in w.value]
    assert len(msgs) == 1 and expect in msgs[0] and "smoke.png" in msgs[0], [w.value for w in at.warning]


def test_history_page_empty(repo):
    at = _page("history.render")
    assert any("まだ実行していません" in i.value for i in at.info)


def test_recipes_editor_reloads_file_changed_elsewhere(repo):
    at = _page("recipes_page.render")
    (repo / "actions/grade.json").write_text('[{"command": "image.adjustments.invert"}]\n', encoding="utf-8")
    at.run()
    assert "image.adjustments.invert" in at.text_area[0].value  # 未編集なら読み直す
    at.text_area[0].input('[{"command": "filter.sharpen.smartSharpen"}]').run()
    (repo / "actions/grade.json").write_text('[{"command": "filter.blur.gaussianBlur"}]\n', encoding="utf-8")
    at.run()
    assert "smartSharpen" in at.text_area[0].value  # 編集中の内容は消さない
    assert any("別の場所で変更されました" in w.value for w in at.warning)


@pytest.fixture
def repo_p2(repo):
    """最新版 v10.0.0 も導入済み。ただし全レシピが失敗する（破壊的変更の入った版のふり）。"""
    write_mock_cli(repo / ".bin" / "v10.0.0" / "mock" / "photocraft-cli", fail=True)
    return repo


def test_smoke_page_detects_breaking_change(repo_p2, monkeypatch):
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v10.0.0", False), releases.Release("v0.2.0", False)], "テスト"))
    write_mock_cli(repo_p2 / ".bin" / "v0.2.0" / "mock" / "photocraft-cli")  # ピン版は正常
    at = _page("smoke_page.render")
    assert not at.error
    next(b for b in at.button if b.label == "スモークテストを実行").click().run()
    run = at.session_state["smoke_run"]
    end = time.time() + 30
    while not run.verdict and time.time() < end:
        time.sleep(0.1)
    at.run()
    assert not at.exception
    assert any("破壊的変更があります" in e.value for e in at.error)  # 受け入れ基準 4
    table = at.dataframe[0].value
    assert table["判定"].tolist() == ["破壊的変更"] and table["v10.0.0"].tolist() == ["失敗"]
    assert at.dataframe[1].value["判定"].tolist() == ["破壊的変更"]  # これまでの結果


def test_smoke_page_requires_installed_versions(repo):
    at = _page("smoke_page.render")  # ピン v0.2.0 も最新 v10.0.0 も未導入
    assert any("未導入の版があります" in w.value for w in at.warning)
    assert next(b for b in at.button if b.label == "スモークテストを実行").disabled


def test_upstream_page_shows_changes_and_records_ack(repo_p2, monkeypatch):
    c = upstream.Commit("a" * 40, "2026-10-05T10:00:00Z")

    def fake_check(root, pinned, mirror):
        s = upstream.Status("2026-10-06T09:00:00+09:00", pinned, "v10.0.0", newer=["v10.0.0"], commits=12, notes=["テスト"])
        s.watched = [upstream.Watched(p, upstream.recorded_sha(root, p), c) for p in ["README.md", "AGENTS.md"]]
        return s

    monkeypatch.setattr(upstream, "check", fake_check)
    at = _page("upstream_page.render")
    assert any("まだ確認していません" in x.value for x in at.caption)
    next(b for b in at.button if b.label == "今すぐ確認").click().run()
    assert not at.exception
    assert any("ピンより新しいリリース" in w.value for w in at.warning)
    assert any("/compare/v0.2.0...v10.0.0" in m.value for m in at.markdown)  # 受け入れ基準 5
    assert [m.value for m in at.metric][:3] == ["v0.2.0", "v10.0.0", "12"]
    next(b for b in at.button if b.label == "確認済みにする").click().run()
    assert (repo_p2 / ".upstream" / "README_md.sha").read_text(encoding="utf-8").strip() == "a" * 40
    assert sum(b.label == "確認済みにする" for b in at.button) == 1  # AGENTS.md だけ残る
    # コマンド台帳: ピンはスナップショット、最新はモック（同じ内容）→ 影響なし
    assert any("削除・書式変更はありません" in x.value for x in at.success)


# ---- P3: ピン更新 / MCP / コマンド台帳 / Issue ------------------------------------------------

from craft_app import issues, mcp, snapshot  # noqa: E402
from test_issues import FakeSession  # noqa: E402


def _wait_smoke(at, timeout=30):
    run = at.session_state["smoke_run"]
    end = time.time() + timeout
    while not run.verdict and time.time() < end:
        time.sleep(0.1)
    assert run.verdict
    at.run()
    return run


@pytest.fixture
def upgrade_repo(repo_p2, monkeypatch):
    """ピンは v9.9.9、更新先は v10.0.0。どちらもモック CLI を導入済み（v10.0.0 は壊れていない版）。"""
    (repo_p2 / ".photocraft-version").write_text("v9.9.9\n", encoding="utf-8")
    write_mock_cli(repo_p2 / ".bin" / "v10.0.0" / "mock" / "photocraft-cli")  # 失敗しない版で作り直す
    (repo_p2 / "samples/smoke/in").mkdir(parents=True, exist_ok=True)
    c = upstream.Commit("a" * 40, "2026-10-05T10:00:00Z")

    def fake_check(root, pinned, mirror):
        s = upstream.Status("2026-10-06T09:00:00+09:00", pinned, "v10.0.0", newer=["v10.0.0"], commits=12, notes=["テスト"])
        s.watched = [upstream.Watched(p, upstream.recorded_sha(root, p), c) for p in ["README.md", "AGENTS.md"]]
        return s

    monkeypatch.setattr(upstream, "check", fake_check)
    return repo_p2


def test_upgrade_wizard_opens_each_gate_in_order(upgrade_repo, monkeypatch):
    made = []
    monkeypatch.setattr(snapshot, "create", lambda tag, cli, root: made.append(tag) or (root / tag))
    at = _page("upgrade_page.render")
    apply_btn = lambda: next(b for b in at.button if b.label.startswith("ピンを v9.9.9"))  # noqa: E731
    assert apply_btn().disabled  # 何もしていない状態では更新できない
    # ① 本家を確認 → 確認済みにする → 読んだ
    next(b for b in at.button if b.label == "本家を確認").click().run()
    next(b for b in at.button if b.label.startswith("すべて確認済みにする")).click().run()
    assert (upgrade_repo / ".upstream/README_md.sha").read_text(encoding="utf-8").strip() == "a" * 40
    at.checkbox(key="upg_reviewed:v9.9.9:v10.0.0").check().run()
    assert apply_btn().disabled and any("スモークテストがまだありません" in m.value for m in at.markdown)
    # ② スモークテスト
    next(b for b in at.button if b.label == "スモークテストを実行").click().run()
    _wait_smoke(at)
    assert apply_btn().disabled  # ③ がまだ
    # ③ 見直し
    at.checkbox(key="upg_step3:v9.9.9:v10.0.0").check().run()
    assert not apply_btn().disabled  # 4 つそろった
    at.checkbox(key="upg_mark:v10.0.0").uncheck()
    at.text_input(key="upg_fix:v10.0.0").input("なし").run()
    apply_btn().click().run()
    assert not at.exception and not at.error
    assert (upgrade_repo / ".photocraft-version").read_text(encoding="utf-8").strip() == "v10.0.0"
    log = (upgrade_repo / "docs/upgrade-log.md").read_text(encoding="utf-8")
    assert "| v9.9.9 | v10.0.0 |" in log
    assert made == ["v10.0.0"]


def test_upgrade_wizard_recipe_edit_after_smoke_reopens_the_gate(upgrade_repo):
    at = _page("upgrade_page.render")
    next(b for b in at.button if b.label == "本家を確認").click().run()
    next(b for b in at.button if b.label.startswith("すべて確認済みにする")).click().run()
    at.checkbox(key="upg_reviewed:v9.9.9:v10.0.0").check().run()
    next(b for b in at.button if b.label == "スモークテストを実行").click().run()
    _wait_smoke(at)
    at.checkbox(key="upg_step3:v9.9.9:v10.0.0").check().run()
    assert not next(b for b in at.button if b.label.startswith("ピンを v9.9.9")).disabled
    (upgrade_repo / "actions/grade.json").write_text('[{"command": "image.adjustments.invert"}]\n', encoding="utf-8")  # スモークのあとに直した
    at.run()
    assert next(b for b in at.button if b.label.startswith("ピンを v9.9.9")).disabled
    shown = [e.value for e in [*at.warning, *at.info, *at.markdown]]
    assert any("レシピが変わりました" in v for v in shown), shown  # 理由を画面に出す


def test_upgrade_wizard_says_so_when_pin_is_latest(repo):
    (repo / ".photocraft-version").write_text("v10.0.0\n", encoding="utf-8")
    at = _page("upgrade_page.render")
    assert any("最新です" in s.value for s in at.success)


def test_mcp_page_requires_existing_root_folders(repo):
    """本家 v0.2.0 はルートのフォルダが無いと起動に失敗する。先に気づけて、作れること。"""
    assert not (repo / "samples" / "out").exists()
    at = _page("mcp_page.render")
    assert any("書き出しルートのフォルダがありません" in e.value for e in at.error)
    assert next(b for b in at.button if b.label == "起動して確かめる").disabled
    next(b for b in at.button if b.label == "ルートのフォルダを作る").click().run()
    assert (repo / "samples" / "out").is_dir()
    assert not at.error and not next(b for b in at.button if b.label == "起動して確かめる").disabled


def test_mcp_page_probes_and_saves_tools(repo):
    (repo / "samples" / "out").mkdir(parents=True)
    at = _page("mcp_page.render")
    assert any("--automation-read-root" in c.value for c in at.code)  # v9.9.9 は roots 対応とみなす
    next(b for b in at.button if b.label == "起動して確かめる").click().run()
    assert not at.exception
    assert any("起動できました: photocraft 9.9.9" in s.value and "公開ツール 2 個" in s.value for s in at.success)
    next(b for b in at.button if b.label.startswith("ツール一覧を保存")).click().run()
    saved = repo / "mcp" / "tools-v9.9.9.json"
    assert [t["name"] for t in json.loads(saved.read_text(encoding="utf-8"))] == ["command_run", "doc_open"]
    at.run()
    assert any("保存済みの一覧と同じ" in c.value for c in at.caption)


def test_mcp_page_bridge_validates_and_reports_connection_failure(repo):
    (repo / "samples" / "out").mkdir(parents=True)
    at = _page("mcp_page.render")
    at.radio(key="mcp_mode").set_value("ブリッジ（起動中の PhotoCraft アプリを操作）").run()
    assert any("--control-token-file" in c.value for c in at.code)
    assert not any("--control-token " in c.value for c in at.code)  # トークンの値を渡す形は出さない
    codes = [c.value for c in at.code]
    client = next(c for c in codes if '"mcpServers"' in c)
    assert "--bridge" in client and "--automation-read-root" not in client  # ブリッジの mcp はルートを使わない
    app = next(c for c in codes if c.startswith("photocraft --control"))
    assert "--automation-read-root" in app and "--automation-write-root" in app  # ルートはアプリ側に渡す
    at.text_input(key="mcp_bridge").input("0.0.0.0:7878").run()
    assert any("loopback" in e.value for e in at.error)
    assert next(b for b in at.button if b.label == "起動して確かめる").disabled
    at.text_input(key="mcp_bridge").input("127.0.0.1:7878").run()
    next(b for b in at.button if b.label == "起動して確かめる").click().run()
    assert any("接続できませんでした" in e.value and "connection refused" in e.value for e in at.error)


def test_mcp_page_warns_for_versions_without_roots(repo):
    write_mock_cli(repo / ".bin" / "v0.1.1" / "mock" / "photocraft-cli")
    at = _page("mcp_page.render")
    at.sidebar.selectbox(key="tag").select("v0.1.1").run()
    assert any("黙って無視" in w.value for w in at.warning)
    assert not any("--automation-read-root" in c.value for c in at.code)


def test_ledger_page_collects_and_saves_without_touching_the_rest(repo):
    at = _page("ledger_page.render")
    assert not at.exception
    (repo / "docs").mkdir(exist_ok=True)
    src = (repo / "docs/commands.md")
    src.write_text("# 台帳\n\n注意書き\n\n| コマンド | params（例） | 用途 | 使用レシピ | 検証日 |\n|---|---|---|---|---|\n| a.b | {} | 手書き | | |\n\n## 版間の変化\n- メモ\n", encoding="utf-8")
    at = _page("ledger_page.render")
    next(b for b in at.button if b.label == "レシピから収集").click().run()
    assert any("追加" in i.value for i in at.info)
    next(b for b in at.button if b.label == "保存").click().run()
    text = src.read_text(encoding="utf-8")
    assert "| filter.sharpen.smartSharpen |" in text and "| a.b | {} | 手書き |" in text
    assert text.startswith("# 台帳\n\n注意書き\n") and text.endswith("## 版間の変化\n- メモ\n")  # 表の外は変わらない


def test_ledger_page_updates_verified_dates_from_history(repo):
    at = _page("ledger_page.render")
    from views import common

    mgr = common.manager()
    job = mgr.start_batch(common.current().cli, "v9.9.9", "", repo / "actions/grade.json", "h", repo / "samples/smoke/in", repo / "out/x")
    end = time.time() + 20
    while not job.done and time.time() < end:
        time.sleep(0.1)
    assert not (repo / "docs/commands.md").exists()  # 台帳がなくても動く（保存で作る）
    next(b for b in at.button if b.label == "レシピから収集").click().run()
    next(b for b in at.button if b.label == "成功した実行から検証日を更新").click().run()
    next(b for b in at.button if b.label == "保存").click().run()
    text = (repo / "docs/commands.md").read_text(encoding="utf-8")
    assert "| コマンド | params（例） | 用途 | 使用レシピ | 検証日 |" in text
    assert "| filter.sharpen.smartSharpen | {\"amount\":80} |" in text and "| grade | " in text and "(v9.9.9) |" in text


@pytest.fixture
def issue_env(repo_p2, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "SECRET-TOKEN")
    (repo_p2.parent / "data").mkdir(exist_ok=True)
    from craft_app import settings as st_settings

    st_settings.save(repo_p2.parent / "data" / "settings.json", {"issue_repo": "o/r", "auto_issue": False})
    sess = FakeSession()
    monkeypatch.setattr(issues.requests, "Session", lambda: sess)
    return sess


def test_upstream_page_files_issues_once_and_never_shows_the_token(issue_env, monkeypatch):
    c = upstream.Commit("b" * 40, "2026-10-05T10:00:00Z")

    def fake_check(root, pinned, mirror):
        s = upstream.Status("2026-10-06T09:00:00+09:00", pinned, "v10.0.0", newer=["v10.0.0"], commits=12)
        s.watched = [upstream.Watched("README.md", None, c)]
        return s

    monkeypatch.setattr(upstream, "check", fake_check)
    at = _page("upstream_page.render")
    next(b for b in at.button if b.label == "今すぐ確認").click().run()
    btn = next(b for b in at.button if b.label.startswith("未起票を起票"))
    assert not btn.disabled
    btn.click().run()
    posts = [c for c in issue_env.calls if c[0] == "post" and c[1].endswith("/issues")]
    assert [p[3]["title"] for p in posts] == ["[upstream] release v10.0.0 (pinned: v0.2.0)", "[upstream] README.md changed (bbbbbbb)"]
    assert all(p[1] == "https://api.github.com/repos/o/r/issues" for p in posts)
    at.run()
    shown = " ".join(str(getattr(e, "value", "")) for e in at.main)
    assert "SECRET-TOKEN" not in shown


def test_issue_button_is_disabled_without_a_token(repo_p2, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from craft_app import secrets as sec

    monkeypatch.setattr(sec, "keyring", None)
    monkeypatch.setattr(upstream, "check", lambda root, pinned, mirror: upstream.Status("t", pinned, "v10.0.0", newer=["v10.0.0"], commits=1))
    at = _page("upstream_page.render")
    next(b for b in at.button if b.label == "今すぐ確認").click().run()
    assert next(b for b in at.button if b.label.startswith("未起票を起票")).disabled
    assert any("未設定" in i.value for i in at.info)  # 起票先かトークン、足りないものを案内する


def test_smoke_page_files_an_issue_for_a_breaking_change(issue_env, repo_p2, monkeypatch):
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v10.0.0", False), releases.Release("v0.2.0", False)], "テスト"))
    write_mock_cli(repo_p2 / ".bin" / "v0.2.0" / "mock" / "photocraft-cli")
    at = _page("smoke_page.render")
    next(b for b in at.button if b.label == "スモークテストを実行").click().run()
    _wait_smoke(at)
    next(b for b in at.button if b.label == "Issue を起票").click().run()
    posts = [c for c in issue_env.calls if c[0] == "post" and c[1].endswith("/issues")]
    assert [p[3]["title"] for p in posts] == ["[upstream] smoke failed on latest (v10.0.0)"]


def test_background_check_auto_files_only_when_enabled(issue_env, repo_p2, monkeypatch):
    from craft_app import settings as st_settings
    from views import common

    c = upstream.Commit("b" * 40, "2026-10-05T10:00:00Z")

    def fake_check(root, pinned, mirror):
        s = upstream.Status("t", pinned, "v10.0.0", newer=["v10.0.0"], commits=3)
        s.watched = [upstream.Watched("README.md", None, c)]
        return s

    monkeypatch.setattr(upstream, "check", fake_check)
    s = common._check_and_file()
    assert not [c for c in issue_env.calls if c[0] == "post"] and s.notes == []  # 既定はオフ
    st_settings.save(common.settings_path(), {"issue_repo": "o/r", "auto_issue": True})
    s = common._check_and_file()
    assert len([c for c in issue_env.calls if c[0] == "post" and c[1].endswith("/issues")]) == 2
    assert any("自動起票: 2 件を起票" in n for n in s.notes)
    s = common._check_and_file()  # もう一度確認しても、同じ件名は起票しない
    assert len([c for c in issue_env.calls if c[0] == "post" and c[1].endswith("/issues")]) == 2


def test_whole_app_boots_and_registers_every_page(repo):
    """streamlit_app.py 全体を起動する（9 画面の登録・区分け・サイドバーの組み立て）。"""
    from pathlib import Path as P

    script = P(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    at = AppTest.from_file(str(script), default_timeout=60)
    at.run()
    assert not at.exception
    from views import common

    assert set(common.PAGES) == {"batch", "recipes", "history", "smoke", "upstream", "upgrade", "versions", "ledger", "mcp"}
    assert any("使用バージョン" in s.label for s in at.sidebar.selectbox)


def test_ledger_editor_rows_keep_new_commands_and_drop_blank_ones():
    """表エディタの結果（pandas）から台帳の行を作る。追加された行は残し、コマンドが空の行・NaN は捨てる。"""
    import pandas as pd

    from views import ledger_page

    df = pd.DataFrame(
        [
            {"コマンド": "a.b", "params（例）": "{}", "用途": "手書き | 注意", "使用レシピ": "grade", "検証日": "2026-10-06 (v0.2.0)"},
            {"コマンド": "image.adjustments.invert", "params（例）": None, "用途": None, "使用レシピ": None, "検証日": None},  # 追加した行
            {"コマンド": "", "params（例）": "x", "用途": "", "使用レシピ": "", "検証日": ""},  # コマンドが空
            {"コマンド": None, "params（例）": None, "用途": None, "使用レシピ": None, "検証日": None},  # 空の追加行
            {"コマンド": float("nan"), "params（例）": float("nan"), "用途": float("nan"), "使用レシピ": float("nan"), "検証日": float("nan")},
        ]
    )
    rows = ledger_page._rows_from(df)
    assert [r.command for r in rows] == ["a.b", "image.adjustments.invert"]
    assert rows[0].purpose == "手書き | 注意" and rows[1].params == "" and rows[1].verified == ""
