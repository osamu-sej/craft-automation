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


def test_v0_3_0_only_forms_are_warned_about():
    """v0.3.0 からの書き方は通すが、v0.2.0 以前ではエラーになるので警告する。"""
    for text in ['{"steps": ["image.adjustments.invert"]}', '[["image.adjustments.invert", {}]]', '{"action": {"steps": [{"command": "a"}]}}']:
        v = recipes.validate(text)
        assert v.ok and len(v.steps) == 1
        assert any("v0.3.0 以降でだけ読める" in w for w in v.warnings), (text, v.warnings)
    for text in ['[{"command": "a"}]', '{"tested_with": "v0.2.0", "actions": [{"id": "a"}]}']:
        assert recipes.validate(text).warnings == []  # 全版で読める書き方には出さない


def test_no_v0_3_0_warning_on_top_of_an_error():
    v = recipes.validate('{"steps": ["a", 1]}')
    assert not v.ok and not any("v0.3.0" in w for w in v.warnings)


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


HAND_WRITTEN = """{
  "tested_with": "v0.2.0",
  "actions": [
    {"command": "filter.sharpen.smartSharpen", "params": {"amount": 80}},
    {"command": "layer.newAdjustmentLayer.curves", "params": {"points": [[0, 0], [64, 56], [255, 255]]}}
  ]
}
"""


def test_mark_tested_keeps_the_formatting(tmp_path):
    """tested_with を更新しても、手書きの書式（1 行ずつのステップ）は崩さない。差分は 1 行だけ。"""
    f = tmp_path / "a.json"
    f.write_text(HAND_WRITTEN, encoding="utf-8")
    recipes.mark_tested(f, "v0.3.0")
    assert f.read_text(encoding="utf-8") == HAND_WRITTEN.replace("v0.2.0", "v0.3.0")


@pytest.mark.parametrize(
    "before,after",
    [
        ('{"actions": [{"command": "a"}]}\n', '{"tested_with": "v0.3.0", "actions": [{"command": "a"}]}\n'),
        ('{\n  "actions": [\n    {"command": "a"}\n  ]\n}\n', '{\n  "tested_with": "v0.3.0",\n  "actions": [\n    {"command": "a"}\n  ]\n}\n'),
        ('{"tested_with":"v0.1.0","actions":[{"command":"a"}]}', '{"tested_with":"v0.3.0","actions":[{"command":"a"}]}\n'),
    ],
)
def test_mark_tested_adds_or_replaces_in_place(tmp_path, before, after):
    f = tmp_path / "a.json"
    f.write_text(before, encoding="utf-8")
    recipes.mark_tested(f, "v0.3.0")
    assert f.read_text(encoding="utf-8") == after
    assert recipes.validate(after).tested_with == "v0.3.0"


def test_mark_tested_falls_back_to_a_rewrite_when_the_text_edit_cannot_be_verified(tmp_path):
    f = tmp_path / "a.json"
    # 配列形式は、オブジェクト形式への変換なので書き直す
    f.write_text('[{"command": "a"}]', encoding="utf-8")
    recipes.mark_tested(f, "v0.3.0")
    assert json.loads(f.read_text(encoding="utf-8")) == {"tested_with": "v0.3.0", "actions": [{"command": "a"}]}
    # params の中に同じ名前のキーがあっても、上位の tested_with を正しく更新する（書き直しになってもよい）
    f.write_text('{"actions": [{"command": "a", "params": {"tested_with": "x"}}], "tested_with": "v0.1.0"}', encoding="utf-8")
    recipes.mark_tested(f, "v0.3.0")
    got = json.loads(f.read_text(encoding="utf-8"))
    assert got["tested_with"] == "v0.3.0" and got["actions"][0]["params"] == {"tested_with": "x"}
    # 空のオブジェクトは、キーを足せる形に直す
    f.write_text("{}", encoding="utf-8")
    recipes.mark_tested(f, "v0.3.0")
    assert json.loads(f.read_text(encoding="utf-8")) == {"tested_with": "v0.3.0"}
