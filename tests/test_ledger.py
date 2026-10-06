from craft_app import ledger, recipes
from craft_app import photocraft as pc


def _recipe(tmp_path, name, steps):
    import json

    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(steps), encoding="utf-8")
    return recipes.Recipe(name, p, p.read_text(encoding="utf-8"))


def test_repo_ledger_round_trips_exactly(repo_root):
    """今の docs/commands.md を読んで書き戻しても、1 文字も変わらない（表の外も含めて）。"""
    text = (repo_root / "docs/commands.md").read_text(encoding="utf-8")
    led = ledger.parse(text)
    assert [r.command for r in led.rows][:2] == ["filter.sharpen.smartSharpen", "layer.newAdjustmentLayer.curves"]
    assert led.render() == text
    assert "版間の変化" in "\n".join(led.after)  # 表の後の文章を保持する


def test_split_cells_handles_escaped_pipes():
    assert ledger.split_cells("| a | b \\| c | d |") == ["a", "b | c", "d"]
    assert ledger.split_cells("|a||c|") == ["a", "", "c"]


def test_pipes_in_cells_survive_a_round_trip():
    led = ledger.parse("# t\n\n| コマンド | params（例） | 用途 | 使用レシピ | 検証日 |\n|---|---|---|---|---|\n| a.b | {} | x | r | |\n\n後\n")
    row = ledger.Row("c.d", '{"mode":"rgb|gray"}', "メモ | 注意", "r", "")
    led.rows.append(row)
    again = ledger.parse(led.render())
    assert again.rows[-1] == row
    assert again.after == ["", "後"]


def test_old_four_column_table_is_upgraded():
    old = "# 台帳\n\n| コマンド | params | 用途 | 検証日 |\n|---|---|---|---|\n| a.b | {} | シャープ | 2026-01-01 |\n"
    led = ledger.parse(old)
    assert led.rows == [ledger.Row("a.b", "{}", "シャープ", "", "2026-01-01")]
    assert "| コマンド | params（例） | 用途 | 使用レシピ | 検証日 |" in led.render()
    assert "| a.b | {} | シャープ |  | 2026-01-01 |" in led.render()


def test_no_table_is_kept_and_can_get_rows():
    led = ledger.parse("# メモだけ\n")
    assert not led.has_table and led.render() == "# メモだけ\n"


def test_collect_adds_updates_and_keeps_manual(tmp_path):
    rows = [
        ledger.Row("filter.sharpen.smartSharpen", '{"amount":80}', "シャープ（手書き）", "grade", "2026-10-05 (v0.2.0)"),
        ledger.Row("file.new", "{}", "新規", "smoke 入力生成", ""),  # レシピ以外の用途は残す
        ledger.Row("old.cmd", "{}", "昔の", "grade", ""),
    ]
    recs = [
        _recipe(tmp_path, "grade", [{"command": "filter.sharpen.smartSharpen", "params": {"amount": 80}}]),
        _recipe(tmp_path, "tone", [{"command": "filter.sharpen.smartSharpen"}, {"command": "image.adjustments.invert"}]),
    ]
    reg = {"image.adjustments.invert": pc.Command("image.adjustments.invert", "Invert", "Image > Adjustments", "{}")}
    got = ledger.collect(rows, recs, reg)
    by = {r.command: r for r in got.rows}
    assert by["filter.sharpen.smartSharpen"].recipes == "grade, tone"
    assert by["filter.sharpen.smartSharpen"].purpose == "シャープ（手書き）"  # 手書きは変えない
    assert by["filter.sharpen.smartSharpen"].verified == "2026-10-05 (v0.2.0)"
    assert by["file.new"].recipes == "smoke 入力生成"
    assert by["old.cmd"].recipes == "" and got.unused == ["old.cmd"]
    assert got.added == ["image.adjustments.invert"]
    new = by["image.adjustments.invert"]
    assert (new.params, new.purpose, new.recipes) == ("{}", "Invert（Image > Adjustments）", "tone")


def test_missing_in_registry():
    reg = {"a": pc.Command("a", "", "", "")}
    assert ledger.missing_in([ledger.Row("a"), ledger.Row("b")], reg) == ["b"]


def test_verified_from_successful_runs():
    runs = [
        {"recipe": "grade", "tag": "v0.2.0", "status": "succeeded", "failed": 0, "ok": 2, "started_at": "2026-10-06T09:00:00+09:00"},
        {"recipe": "grade", "tag": "v0.1.1", "status": "succeeded", "failed": 0, "ok": 1, "started_at": "2026-10-05T09:00:00+09:00"},
        {"recipe": "grade", "tag": "v0.3.0", "status": "failed", "failed": 1, "ok": 0, "started_at": "2026-10-07T09:00:00+09:00"},
        {"recipe": "tone", "tag": "v0.2.0", "status": "succeeded", "failed": 0, "ok": 0, "started_at": "2026-10-07T09:00:00+09:00"},  # 0 件成功は数えない
    ]
    ok = ledger.successes(runs)
    assert ok == {"grade": {"v0.2.0": "2026-10-06", "v0.1.1": "2026-10-05"}}
    rows = [ledger.Row("a", recipes="grade"), ledger.Row("b", recipes="tone"), ledger.Row("c", recipes="smoke 入力生成")]
    out, changed = ledger.with_verified(rows, ok)
    assert out[0].verified == "2026-10-06 (v0.1.1, v0.2.0)" and changed == ["a"]
    assert out[1].verified == "" and out[2].verified == ""
    assert ledger.with_verified(out, ok)[1] == []  # 2 回目は変化なし


def test_save_and_load(tmp_path):
    p = tmp_path / "docs" / "commands.md"
    led = ledger.parse("# t\n")
    led.has_table = True
    led.rows = [ledger.Row("a.b", "{}", "x", "r", "")]
    ledger.save(p, led)
    assert ledger.load(p).rows == led.rows
    assert p.read_bytes().endswith(b"\n") and b"\r" not in p.read_bytes()
