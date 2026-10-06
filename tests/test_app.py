"""画面のテスト（streamlit.testing の AppTest。モック CLI と一時リポジトリで動かす）。"""

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
    monkeypatch.setattr(photocraft, "asset_for", lambda tag, *a: photocraft.Asset("mock.zip", f"mock/{exe}", "zip"))
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
