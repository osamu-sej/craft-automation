import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from craft_app import jobs, photocraft, recipes, releases
from craft_app.paths import Repo

HERE = Path(__file__).resolve().parent


@pytest.fixture
def mock_cli(tmp_path) -> Path:
    """tests/mock_cli.py を、OS ごとに直接起動できる形で包む。"""
    if os.name == "nt":
        cli = tmp_path / "photocraft-cli.bat"
        cli.write_text(f'@"{sys.executable}" "{HERE / "mock_cli.py"}" %*\n', encoding="utf-8")  # Windows ではテキストモードで CRLF になる
    else:
        cli = tmp_path / "photocraft-cli"
        cli.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "mock_cli.py"}" "$@"\n', encoding="utf-8")
        cli.chmod(0o755)
    return cli


@pytest.fixture
def work(tmp_path):
    inp = tmp_path / "in"
    inp.mkdir()
    for n in ["a.png", "b.png", "notes.txt"]:
        (inp / n).write_bytes(b"x")
    return inp, tmp_path / "out"


def _wait(job, timeout=20):
    end = time.time() + timeout
    while not job.done and time.time() < end:
        time.sleep(0.05)
    assert job.done, job.log_text()


def _recipe(tmp_path, actions) -> Path:
    p = tmp_path / "r.json"
    p.write_text(json.dumps(actions), encoding="utf-8")
    return p


def test_successful_batch_is_recorded(tmp_path, mock_cli, work):
    inp, out = work
    hist = jobs.History(tmp_path / "data" / "runs.sqlite")
    mgr = jobs.JobManager(hist)
    r = _recipe(tmp_path, [{"command": "a.b"}])
    job = mgr.start_batch(mock_cli, "v9.9.9", "photocraft-cli 9.9.9", r, "h", inp, out)
    assert job.expected == 2
    _wait(job)
    assert job.status == "succeeded" and job.exit_code == 0
    assert [Path(o).name for _, o in job.ok] == ["a.png", "b.png"]
    assert len(job.warnings) == 2
    row = hist.runs()[0]
    assert (row["status"], row["ok"], row["failed"], row["recipe"], row["tag"]) == ("succeeded", 2, 0, "r", "v9.9.9")
    assert "batch --actions" in row["command"] and "[stdout] ok" in row["log"]
    assert hist.last_by_recipe()["r"]["id"] == job.id


def test_failed_batch(tmp_path, mock_cli, work):
    inp, out = work
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    job = mgr.start_batch(mock_cli, "v9.9.9", "", _recipe(tmp_path, [{"command": "fail.me"}]), "h", inp, out)
    _wait(job)
    assert job.status == "failed" and job.exit_code == 1
    assert len(job.failed) == 2 and "unknown command" in job.failed[0][1]


def test_cancel(tmp_path, mock_cli, work):
    inp, out = work
    hist = jobs.History(tmp_path / "runs.sqlite")
    mgr = jobs.JobManager(hist)
    job = mgr.start_batch(mock_cli, "v9.9.9", "", _recipe(tmp_path, [{"command": "slow"}]), "h", inp, out)
    time.sleep(0.5)
    assert not job.done
    mgr.cancel(job.id)
    _wait(job, 10)
    assert job.status == "cancelled"
    assert hist.runs()[0]["status"] == "cancelled"


def test_missing_cli_is_an_error(tmp_path, work):
    inp, out = work
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    job = mgr.start_batch(tmp_path / "nope", "v9.9.9", "", _recipe(tmp_path, [{"command": "a"}]), "h", inp, out)
    assert job.status == "error" and "起動できません" in job.log_text()


@pytest.mark.integration
def test_real_release_runs_grade_recipe(tmp_path, repo_root):
    """本家 v0.2.0 をこの OS 向けに取得し、grade レシピを smoke 入力に適用する（FR-02/03）。"""
    inst = releases.install("v0.2.0", tmp_path / "bin")
    version = photocraft.cli_version(inst.cli)
    assert version.startswith("photocraft-cli 0.2.0")
    reg = photocraft.load_registry(inst.cli)
    recipe = repo_root / "actions" / "grade.json"
    v = recipes.validate(recipe.read_text(encoding="utf-8"), reg)
    assert v.ok and v.warnings == []
    inp = tmp_path / "in"
    shutil.copytree(repo_root / "samples" / "smoke" / "in", inp)
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    job = mgr.start_batch(inst.cli, "v0.2.0", version, recipe, "h", inp, tmp_path / "out")
    _wait(job, 120)
    assert job.status == "succeeded", job.log_text()
    assert (tmp_path / "out" / "smoke.png").is_file()
    assert Repo(repo_root).pinned() == "v0.2.0"
