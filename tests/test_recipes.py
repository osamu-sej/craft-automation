import json

import pytest

from craft_app import photocraft as pc
from craft_app import recipes

REG = {
    "filter.sharpen.smartSharpen": pc.Command("filter.sharpen.smartSharpen", "Smart Sharpen…", "Filter > Sharpen", '{"amount":1..500=100,"radius":0.1..64=1}'),
    "image.adjustments.invert": pc.Command("image.adjustments.invert", "Invert", "Image > Adjustments", "{}"),
}


def test_invalid_json_is_an_error():
    v = recipes.validate('[{"command": "a",}]')
    assert not v.ok and "構文エラー（1 行 18 列）" in v.errors[0]


def test_unknown_command_and_key_are_warnings():
    text = json.dumps([{"command": "filter.sharpen.smartSharpen", "params": {"amount": 80, "bogus": 1}}, {"command": "no.such"}])
    v = recipes.validate(text, REG)
    assert v.ok
    assert any("bogus" in w for w in v.warnings)
    assert any("no.such" in w for w in v.warnings)


def test_tested_with_must_be_string():
    assert recipes.validate('{"tested_with": "v0.2.0", "actions": [{"command": "a"}]}').tested_with == "v0.2.0"
    assert not recipes.validate('{"tested_with": 2, "actions": [{"command": "a"}]}').ok


def test_save_rejects_invalid_and_existing(tmp_path):
    with pytest.raises(ValueError):
        recipes.save(tmp_path, "x", "{", overwrite=False)
    assert not (tmp_path / "x.json").exists()
    recipes.save(tmp_path, "x", '[{"command": "a"}]', overwrite=False)
    with pytest.raises(FileExistsError):
        recipes.save(tmp_path, "x", '[{"command": "a"}]', overwrite=False)
    recipes.save(tmp_path, "x", '[{"command": "b"}]', overwrite=True)
    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == [{"command": "b"}]


@pytest.mark.parametrize("name,ok", [("grade", True), ("色調-補正_1", True), ("a/b", False), (".x", False), ("", False), ('a"b', False)])
def test_check_name(name, ok):
    assert (recipes.check_name(name) is None) == ok


def test_mark_tested_converts_array(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('[{"command": "a"}]', encoding="utf-8")
    recipes.mark_tested(p, "v0.2.0")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"tested_with": "v0.2.0", "actions": [{"command": "a"}]}
    recipes.mark_tested(p, "v0.3.0")
    assert json.loads(p.read_text(encoding="utf-8"))["tested_with"] == "v0.3.0"
    # CLI と同じ解釈で読めること（FR-09）
    assert pc.parse_actions(json.loads(p.read_text(encoding="utf-8")))[1] == []


def test_append_step():
    out = recipes.append_step('{"actions": []}', "image.adjustments.invert")
    assert json.loads(out)["actions"] == [{"command": "image.adjustments.invert", "params": {}}]
    with pytest.raises(ValueError):
        recipes.append_step('{"x": 1}', "a")


def test_list_recipes_reads_repo(repo_root):
    names = [r.name for r in recipes.list_recipes(repo_root / "actions")]
    assert "grade" in names
