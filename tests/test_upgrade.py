import json
import shutil

import pytest

from craft_app import jobs, recipes, smoke, upgrade
from craft_app import upstream as up
from craft_app.paths import Repo
from craft_app.releases import Installed
from conftest import write_mock_cli

C = up.Commit("a" * 40, "2026-10-05T00:00:00Z")
GOOD = {"verdict": "互換（ピンを更新してよい）", "recipes_hash": "H"}


def watched(*statuses):
    """statuses: 'ok' / 'changed' / 'unrecorded' / 'failed'"""
    out = []
    for i, s in enumerate(statuses):
        rec = {"ok": "a" * 40, "changed": "old", "unrecorded": None, "failed": None}[s]
        out.append(up.Watched(f"f{i}.md", rec, None if s == "failed" else C))
    return out


def gates(**kw):
    base = dict(reviewed=True, step3_done=True, watched=watched("ok"), smoke_row=GOOD, recipes_hash="H")
    base.update(kw)
    return upgrade.evaluate("v0.1.1", "v0.2.0", **base)


def test_all_steps_done_is_ready():
    g = gates()
    assert g.ready and g.blockers() == []


@pytest.mark.parametrize(
    "kw,text",
    [
        (dict(reviewed=False), "手順 1"),
        (dict(step3_done=False), "手順 3"),
        (dict(watched=watched("ok", "changed")), "確認済みにしていない監視対象が 1 件"),
        (dict(watched=watched("unrecorded")), "確認済みにしていない監視対象が 1 件"),
        (dict(watched=watched("failed")), "取得できなかった監視対象が 1 件"),
        (dict(watched=None), "取得できなかった"),
        (dict(smoke_row=None), "スモークテストがまだありません"),
        (dict(smoke_row={"verdict": "破壊的変更", "recipes_hash": "H"}), "破壊的変更"),
        (dict(smoke_row={"verdict": "要確認", "recipes_hash": "H"}), "要確認"),
        (dict(recipes_hash="CHANGED"), "レシピが変わりました"),
    ],
)
def test_each_step_blocks_the_pin_update(kw, text):
    g = gates(**kw)
    assert not g.ready
    assert any(text in b for b in g.blockers()), g.blockers()


def test_same_version_is_blocked():
    g = upgrade.evaluate("v0.2.0", "v0.2.0", reviewed=True, step3_done=True, watched=[], smoke_row=GOOD, recipes_hash="H")
    assert not g.ready and "ピンと同じ" in g.blockers()[0]


def test_append_log_adds_a_row_after_the_table():
    base = "# アップグレード履歴\n\n| 日付 | from | to | 結果 | 修正内容 |\n|---|---|---|---|---|\n| 2026-10-05 | - | v0.1.1 | 初期ピン | リポジトリ作成 |\n"
    out = upgrade.append_log(base, "2026-10-06", "v0.1.1", "v0.2.0", "互換", "MCP | 設定\n追記")
    assert out.endswith("| 2026-10-06 | v0.1.1 | v0.2.0 | 互換 | MCP \\| 設定 追記 |\n")
    assert out.startswith(base.rstrip("\n"))
    with_note = base + "\n※ 手書きのメモ\n"
    out = upgrade.append_log(with_note, "d", "a", "b", "r", "f")
    assert out.index("| d | a | b | r | f |") < out.index("※ 手書きのメモ")  # 表の直後に入る
    assert upgrade.append_log("", "d", "a", "b", "r", "f").startswith("# アップグレード履歴")


@pytest.fixture
def repo(tmp_path, repo_root):
    root = tmp_path / "repo"
    for d in ["actions", "samples/smoke/in", "docs"]:
        shutil.copytree(repo_root / d, root / d, ignore=shutil.ignore_patterns("upstream-snapshot"))
    (root / ".photocraft-version").write_text("v0.1.1\n", encoding="utf-8")
    return Repo(root)


def ready_gates():
    return upgrade.evaluate("v0.1.1", "v0.2.0", reviewed=True, step3_done=True, watched=watched("ok"), smoke_row=GOOD, recipes_hash="H")


def test_apply_refuses_when_a_gate_is_open_and_changes_nothing(repo):
    before = {p: p.read_bytes() for p in repo.root.rglob("*") if p.is_file()}
    with pytest.raises(upgrade.GateError, match="手順 3"):
        upgrade.apply(repo, gates(step3_done=False), result="r", fix="f")
    assert {p: p.read_bytes() for p in repo.root.rglob("*") if p.is_file()} == before
    assert repo.pinned() == "v0.1.1"


def test_apply_updates_pin_log_tested_with_and_snapshot(repo):
    made = []

    def snap():
        d = repo.snapshot_dir / "v0.2.0"
        d.mkdir(parents=True)
        made.append(d)
        return d

    res = upgrade.apply(repo, ready_gates(), result="互換", fix="なし", make_snapshot=snap, today="2026-10-06")
    assert repo.pinned() == "v0.2.0" and (repo.root / ".photocraft-version").read_bytes() == b"v0.2.0\n"
    assert "| 2026-10-06 | v0.1.1 | v0.2.0 | 互換 | なし |" in (repo.root / "docs/upgrade-log.md").read_text(encoding="utf-8")
    assert recipes.validate((repo.actions_dir / "grade.json").read_text(encoding="utf-8")).tested_with == "v0.2.0"
    assert res.changed[0] == "docs/upstream-snapshot/v0.2.0/" and res.changed[-1] == ".photocraft-version" and "actions/grade.json" in res.changed


def test_failed_snapshot_leaves_the_pin_alone(repo):
    def boom():
        raise RuntimeError("取得失敗")

    log = repo.root / "docs/upgrade-log.md"
    before = log.read_bytes()
    with pytest.raises(RuntimeError, match="取得失敗"):
        upgrade.apply(repo, ready_gates(), result="r", fix="f", make_snapshot=boom)
    assert repo.pinned() == "v0.1.1"
    assert log.read_bytes() == before  # 履歴も変えない


def test_stale_screen_is_rejected(repo):
    repo.pin_file.write_text("v0.1.5\n", encoding="utf-8")  # 画面を開いたあとにピンが変わった
    with pytest.raises(upgrade.GateError, match="v0.1.5"):
        upgrade.apply(repo, ready_gates(), result="r", fix="f")


def test_smoke_gate_follows_recipe_changes_end_to_end(tmp_path, repo):
    """スモークの結果が「今のレシピ」に対するものかを、実際の履歴で確かめる。"""
    pinned = Installed("v1.0.0", write_mock_cli(tmp_path / "a/photocraft-cli"))
    latest = Installed("v1.1.0", write_mock_cli(tmp_path / "b/photocraft-cli"))
    hist = jobs.History(tmp_path / "runs.sqlite")
    mgr = jobs.JobManager(hist)
    run = smoke.start(mgr, repo, pinned, latest, {})
    import time

    end = time.time() + 30
    while not run.verdict and time.time() < end:
        time.sleep(0.1)
    now = recipes.collection_hash(recipes.list_recipes(repo.actions_dir))
    ok, why = upgrade.smoke_gate(hist.latest_smoke("v1.0.0", "v1.1.0"), now, "v1.0.0", "v1.1.0")
    assert ok, why
    # レシピを直したら、スモークをやり直すまで通らない
    (repo.actions_dir / "grade.json").write_text('[{"command": "image.adjustments.invert"}]', encoding="utf-8")
    now2 = recipes.collection_hash(recipes.list_recipes(repo.actions_dir))
    assert now2 != now
    ok, why = upgrade.smoke_gate(hist.latest_smoke("v1.0.0", "v1.1.0"), now2, "v1.0.0", "v1.1.0")
    assert not ok and "レシピが変わりました" in why
    # 別の組み合わせの結果は使えない
    assert upgrade.smoke_gate(hist.latest_smoke("v1.0.0", "v9.9.9"), now, "v1.0.0", "v9.9.9")[0] is False


def test_p2_smoke_table_is_migrated(tmp_path):
    import sqlite3

    db = tmp_path / "runs.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE smokes(id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, pinned TEXT, latest TEXT, verdict TEXT, detail TEXT)")
    c.execute("INSERT INTO smokes VALUES ('x','2026-10-05','','v1','v2','互換（ピンを更新してよい）','[]')")
    c.commit()
    c.close()
    row = jobs.History(db).latest_smoke("v1", "v2")
    assert row["recipes_hash"] == ""  # 古い結果は、どのレシピ集合に対するものか分からない → ゲートは通らない
    assert not upgrade.smoke_gate(row, "H", "v1", "v2")[0]
