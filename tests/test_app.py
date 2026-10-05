"""画面のテスト（streamlit.testing の AppTest。モック CLI と一時リポジトリで動かす）。"""

import os
import shutil
import sys
import time
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from craft_app import photocraft, releases

HERE = Path(__file__).resolve().parent
TAG = "v9.9.9"


@pytest.fixture
def repo(tmp_path, repo_root, monkeypatch):
    root = tmp_path / "repo"
    for d in ["actions", "samples/smoke/in", "docs/upstream-snapshot"]:
        shutil.copytree(repo_root / d, root / d)
    shutil.copy(repo_root / ".photocraft-version", root / ".photocraft-version")
    # この OS で直接起動できるモック CLI を「導入済みの版」として置く
    exe = "photocraft-cli.bat" if os.name == "nt" else "photocraft-cli"
    monkeypatch.setattr(photocraft, "asset_for", lambda tag, *a: photocraft.Asset("mock.zip", f"mock/{exe}", "zip"))
    cli = root / ".bin" / TAG / "mock" / exe
    cli.parent.mkdir(parents=True)
    if os.name == "nt":
        cli.write_text(f'@"{sys.executable}" "{HERE / "mock_cli.py"}" %*\n', encoding="utf-8")  # Windows ではテキストモードで CRLF になる
    else:
        cli.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "mock_cli.py"}" "$@"\n', encoding="utf-8")
        cli.chmod(0o755)
    monkeypatch.setattr(releases, "list_releases", lambda: ([releases.Release("v10.0.0", False, "2026-10-05T00:00:00Z"), releases.Release(TAG, False)], "テスト"))
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
