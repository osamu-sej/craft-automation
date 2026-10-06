"""スモークテスト（FR-04）。受け入れ基準 4: pinned 成功・latest 失敗を「破壊的変更」と判定する（モックで再現）。"""

import json
import shutil
import time

import pytest

from conftest import write_mock_cli
from craft_app import jobs, smoke
from craft_app.paths import Repo
from craft_app.releases import Installed


@pytest.mark.parametrize(
    "pinned,latest,expected",
    [
        (True, True, smoke.COMPATIBLE),
        (True, False, smoke.BREAKING),
        (False, True, smoke.PINNED_FAILS),
        (False, False, smoke.BOTH_FAIL),
        (True, None, smoke.OK),
        (False, None, smoke.NG),
    ],
)
def test_recipe_verdict(pinned, latest, expected):
    assert smoke.recipe_verdict(pinned, latest) == expected


def test_overall():
    assert smoke.overall([smoke.COMPATIBLE, smoke.BREAKING]) == smoke.BREAKING
    assert smoke.overall([smoke.COMPATIBLE] * 2).startswith("互換")
    assert smoke.overall([smoke.OK]).startswith("成功")
    assert smoke.overall([smoke.COMPATIBLE, smoke.BOTH_FAIL]) == "要確認"
    assert smoke.overall([]) == "レシピなし"


@pytest.fixture
def repo(tmp_path, repo_root):
    root = tmp_path / "repo"
    shutil.copytree(repo_root / "actions", root / "actions")
    shutil.copytree(repo_root / "samples/smoke/in", root / "samples/smoke/in")
    (root / "actions/second.json").write_text('[{"command": "image.adjustments.invert"}]', encoding="utf-8")
    return Repo(root)


def _wait(run, mgr, timeout=30):
    end = time.time() + timeout
    while not run.verdict and time.time() < end:
        time.sleep(0.1)
    assert run.verdict


def test_breaking_change_detected(tmp_path, repo):
    good = Installed("v1.0.0", write_mock_cli(tmp_path / "good/photocraft-cli"))
    bad = Installed("v2.0.0", write_mock_cli(tmp_path / "bad/photocraft-cli", fail=True))
    hist = jobs.History(tmp_path / "runs.sqlite")
    mgr = jobs.JobManager(hist)
    run = smoke.start(mgr, repo, good, bad, {"v1.0.0": "mock 1", "v2.0.0": "mock 2"})
    assert len(run.jobs) == 4  # 2 レシピ × 2 版
    _wait(run, mgr)
    assert run.verdict == smoke.BREAKING
    assert [r["判定"] for r in run.table(mgr)] == [smoke.BREAKING, smoke.BREAKING]
    assert (repo.root / "out/smoke/v1.0.0/grade/smoke.png").is_file()
    saved = hist.smokes()[0]
    assert (saved["pinned"], saved["latest"], saved["verdict"]) == ("v1.0.0", "v2.0.0", smoke.BREAKING)
    assert json.loads(saved["detail"])[0]["v2.0.0"] == smoke.NG
    assert {r["kind"] for r in hist.runs()} == {"smoke"}
    assert hist.last_by_recipe() == {}  # スモークはレシピの「最終実行」に数えない


def test_compatible_and_pinned_is_latest(tmp_path, repo):
    a = Installed("v1.0.0", write_mock_cli(tmp_path / "a/photocraft-cli"))
    b = Installed("v1.1.0", write_mock_cli(tmp_path / "b/photocraft-cli"))
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    run = smoke.start(mgr, repo, a, b, {})
    _wait(run, mgr)
    assert run.verdict.startswith("互換")
    same = smoke.start(mgr, repo, a, a, {})
    assert same.latest is None and len(same.jobs) == 2
    _wait(same, mgr)
    assert same.verdict.startswith("成功")


def test_stale_output_does_not_count(tmp_path, repo):
    """前回の出力が残っていても、今回失敗すれば失敗（smoke.sh の rm -rf と同じ）。"""
    stale = repo.root / "out/smoke/v2.0.0/grade"
    stale.mkdir(parents=True)
    (stale / "smoke.png").write_bytes(b"old")
    bad = Installed("v2.0.0", write_mock_cli(tmp_path / "bad/photocraft-cli", fail=True))
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    run = smoke.start(mgr, repo, bad, None, {})
    _wait(run, mgr)
    assert run.verdict == "要確認"
    assert not (stale / "smoke.png").exists()


def test_history_migrates_p1_database(tmp_path):
    """P1 の履歴 DB（kind 列なし）を開いても動く。"""
    import sqlite3

    db = tmp_path / "runs.sqlite"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE runs(id TEXT PRIMARY KEY, recipe TEXT, recipe_hash TEXT, tag TEXT, version TEXT,
        command TEXT, in_dir TEXT, out_dir TEXT, status TEXT, exit_code INTEGER, ok INTEGER, failed INTEGER,
        log TEXT, started_at TEXT, finished_at TEXT)""")
    c.execute("INSERT INTO runs VALUES ('x','grade','h','v0.2.0','','cmd','i','o','succeeded',0,1,0,'','2026-10-05T00:00:00','')")
    c.commit()
    c.close()
    hist = jobs.History(db)
    assert hist.runs()[0]["kind"] == "batch"
    assert hist.last_by_recipe()["grade"]["id"] == "x"
