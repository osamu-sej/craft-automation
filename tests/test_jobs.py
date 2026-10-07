import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from craft_app import jobs, photocraft, recipes, releases
from craft_app.paths import Repo
from conftest import write_mock_cli

HERE = Path(__file__).resolve().parent


@pytest.fixture
def mock_cli(tmp_path) -> Path:
    return write_mock_cli(tmp_path / "photocraft-cli")


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
@pytest.mark.parametrize("which", ["pin", "v0.2.0"])
def test_real_release_runs_grade_recipe(tmp_path, repo_root, which):
    """本家の版をこの OS 向けに取得し、grade レシピを smoke 入力に適用する（FR-02/03）。ピンと、その前の v0.2.0 の両方で。"""
    tag = Repo(repo_root).pinned() if which == "pin" else "v0.2.0"
    if which == "v0.2.0" and tag == Repo(repo_root).pinned():
        pytest.skip("ピンが v0.2.0 のときは、ピンの回で確かめている")
    inst = releases.install(tag, tmp_path / "bin")
    version = photocraft.cli_version(inst.cli)
    assert version.startswith(f"photocraft-cli {tag.lstrip('v')} ")
    reg = photocraft.load_registry(inst.cli)
    recipe = repo_root / "actions" / "grade.json"
    v = recipes.validate(recipe.read_text(encoding="utf-8"), reg)
    assert v.ok and v.warnings == []
    inp = tmp_path / "in"
    shutil.copytree(repo_root / "samples" / "smoke" / "in", inp)
    mgr = jobs.JobManager(jobs.History(tmp_path / "runs.sqlite"))
    job = mgr.start_batch(inst.cli, tag, version, recipe, "h", inp, tmp_path / "out")
    _wait(job, 120)
    assert job.status == "succeeded", job.log_text()
    assert (tmp_path / "out" / "smoke.png").is_file()
