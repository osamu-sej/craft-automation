import json
from pathlib import Path

import pytest

from craft_app import photocraft as pc


@pytest.mark.parametrize(
    "system,machine,name,cli",
    [
        ("Linux", "x86_64", "photocraft-0.2.0-linux-x86_64.tar.gz", "photocraft-0.2.0-linux-x86_64/bin/photocraft-cli"),
        ("Linux", "aarch64", "photocraft-0.2.0-linux-aarch64.tar.gz", "photocraft-0.2.0-linux-aarch64/bin/photocraft-cli"),
        ("Darwin", "arm64", "photocraft-cli-0.2.0-macos-universal.zip", "photocraft-cli-0.2.0-macos-universal/photocraft-cli"),
        ("Darwin", "x86_64", "photocraft-cli-0.2.0-macos-universal.zip", "photocraft-cli-0.2.0-macos-universal/photocraft-cli"),
        ("Windows", "AMD64", "photocraft-0.2.0-windows-x64-portable.zip", "photocraft-0.2.0-windows-x64-portable/photocraft-cli.exe"),
        ("Windows", "x86", "photocraft-0.2.0-windows-x86-portable.zip", "photocraft-0.2.0-windows-x86-portable/photocraft-cli.exe"),
        ("Windows", "ARM64", "photocraft-0.2.0-windows-x64-portable.zip", "photocraft-0.2.0-windows-x64-portable/photocraft-cli.exe"),
    ],
)
def test_asset_names_match_release(system, machine, name, cli, repo_root):
    a = pc.asset_for("v0.2.0", system, machine)
    assert (a.name, a.cli_relpath) == (name, cli)
    # v0.2.0 の実際の asset 一覧（スナップショット）に存在すること
    sums = (repo_root / "docs/upstream-snapshot/v0.2.0/generated/release-assets.txt").read_text(encoding="utf-8")
    assert pc.checksum_for(sums, name) is not None


def test_windows_arm64_native_asset_from_v0_3_0():
    """v0.3.0 のリリースに `windows-arm64-portable.zip` が付いた（実際の SHA256SUMS で確認）。それより前は x64 版で代用する。"""
    names = lambda tag, machine="ARM64": [a.name for a in pc.asset_candidates(tag, "Windows", machine)]  # noqa: E731
    assert names("v0.3.0") == ["photocraft-0.3.0-windows-arm64-portable.zip", "photocraft-0.3.0-windows-x64-portable.zip"]
    assert names("v0.3.0-rc.1")[0] == "photocraft-0.3.0-rc.1-windows-arm64-portable.zip"
    assert names("v0.2.0") == ["photocraft-0.2.0-windows-x64-portable.zip"]
    assert names("v0.3.0", "AMD64") == ["photocraft-0.3.0-windows-x64-portable.zip"]  # x64 の PC は今まで通り
    assert pc.asset_for("v0.3.0", "Windows", "ARM64").cli_relpath == "photocraft-0.3.0-windows-arm64-portable/photocraft-cli.exe"
    assert pc.asset_for("v0.3.0", "Windows", "ARM64").archive == "zip"


def test_assets_exist_in_every_committed_snapshot(repo_root):
    """各版のスナップショットにある SHA256SUMS に、この版の全 OS 向けの最優先 asset が載っている。"""
    snaps = sorted((repo_root / "docs/upstream-snapshot").glob("v*/generated/release-assets.txt"))
    assert snaps
    for f in snaps:
        tag, sums = f.parents[1].name, f.read_text(encoding="utf-8")
        for system, machine in [("Linux", "x86_64"), ("Linux", "aarch64"), ("Darwin", "arm64"), ("Windows", "AMD64"), ("Windows", "x86"), ("Windows", "ARM64")]:
            cands = pc.asset_candidates(tag, system, machine)
            assert any(pc.checksum_for(sums, a.name) for a in cands), (tag, system, machine)
            assert pc.checksum_for(sums, cands[0].name), (tag, system, machine, "最優先の asset が無い")


def test_batch_collision_by_version():
    assert [pc.batch_collision(t) for t in ["v0.1.1", "v0.2.0", "v0.3.0", "v0.3.0-rc.1", "v1.0.0", "nightly"]] == ["overwrite", "overwrite", "fail", "fail", "fail", "overwrite"]


def test_prerelease_tag_and_unsupported():
    assert pc.asset_for("v0.1.1-rc.5", "Linux", "x86_64").name == "photocraft-0.1.1-rc.5-linux-x86_64.tar.gz"
    with pytest.raises(pc.UnsupportedPlatform):
        pc.asset_for("v0.2.0", "FreeBSD", "amd64")
    with pytest.raises(pc.UnsupportedPlatform):
        pc.asset_for("v0.2.0", "Linux", "riscv64")


def test_checksum_for():
    text = "abc  photocraft-0.2.0-linux-x86_64.tar.gz\ndef *other.zip\n"
    assert pc.checksum_for(text, "photocraft-0.2.0-linux-x86_64.tar.gz") == "abc"
    assert pc.checksum_for(text, "other.zip") == "def"
    assert pc.checksum_for(text, "missing.zip") is None


def test_batch_args():
    args = pc.batch_args(Path("cli"), Path("a.json"), Path("in"), Path("out"), "png", 90)
    assert args == ["cli", "batch", "--actions", "a.json", "--in", "in", "--out", "out", "--format", "png", "--quality", "90"]
    assert "--format" not in pc.batch_args(Path("cli"), Path("a.json"), Path("in"), Path("out"))


def _steps(data):
    r = pc.parse_actions_ex(data)
    return [(s.command, s.params) for s in r.steps], r.errors, r.newer


# 実機（v0.2.0 / v0.3.0 の photocraft-cli batch --actions）で受理・拒否を確かめた書き方（2026-10-07）。
# (データ, v0.2.0 が受理する, v0.3.0 が受理する)。`empty_list` だけは CLI が通すが、アプリは「ステップなし」として拒否する。
REAL_FORMS = {
    "old_array_obj": ([{"command": "a.b", "params": {"x": 1}}], True, True),
    "old_array_id": ([{"id": "a.b"}], True, True),
    "old_wrapped": ({"tested_with": "v0.2.0", "actions": [{"command": "a.b"}]}, True, True),
    "pairs": ([["a.b", {"x": 1}]], False, True),
    "pair_no_params": ([["a.b"]], False, True),
    "bare": (["a.b"], False, True),
    "mixed": (["a.b", {"command": "a.b"}, ["a.b", {}]], False, True),
    "steps": ({"steps": ["a.b"]}, False, True),
    "action_steps": ({"action": {"steps": ["a.b"]}}, False, True),
    "action_arr": ({"action": ["a.b"]}, False, True),
    "actions_obj_steps": ({"actions": {"steps": ["a.b"]}}, False, True),
    "actions_obj_action": ({"actions": {"action": ["a.b"]}}, False, True),
    "actions_and_steps": ({"actions": ["a.b"], "steps": [{"command": "a.b"}]}, False, True),
    "no_steps": ({"foo": []}, False, False),
    "steps_not_array": ({"steps": 1}, False, False),
    "action_not_array": ({"action": 1}, False, False),
    "empty_pair": ([[]], False, False),
    "int_step": ([1], False, False),
    "pair_nonstr": ([[1, {}]], False, False),
    "actions_null": ({"actions": None}, False, False),
    "obj_no_command": ([{"params": {}}], False, False),
    "command_nonstr": ([{"command": 3, "id": "a.b"}], False, False),
    "str_top": ("x", False, False),
}


@pytest.mark.parametrize("name", REAL_FORMS)
def test_parse_actions_agrees_with_the_real_cli(name):
    data, v020, v030 = REAL_FORMS[name]
    r = pc.parse_actions_ex(data)
    assert (not r.errors) is v030  # v0.3.0 が通す書き方は、アプリも通す
    assert (not r.errors and not r.newer) is v020  # v0.2.0 でも通るかは newer（v0.3.0 以降専用）で分かる


def test_parse_actions_forms():
    assert _steps([{"command": "a.b", "params": {"x": 1}}, {"id": "c.d"}]) == ([("a.b", {"x": 1}), ("c.d", {})], [], [])
    assert _steps({"tested_with": "v0.2.0", "actions": [{"command": "a.b", "params": {"x": 1}}, {"id": "c.d"}]}) == ([("a.b", {"x": 1}), ("c.d", {})], [], [])


def test_parse_actions_v030_forms():
    steps, errors, newer = _steps({"steps": [["a.b", {"x": 1}], ["c.d"], "e.f", {"command": "g.h"}]})
    assert errors == [] and steps == [("a.b", {"x": 1}), ("c.d", {}), ("e.f", {}), ("g.h", {})]
    assert len(newer) == 3 and any("steps" in n for n in newer) and any("配列" in n for n in newer) and any("文字列" in n for n in newer)
    assert _steps({"action": {"steps": ["a"]}})[2][0] == '{"action": …} 形式'
    assert _steps({"actions": {"steps": [{"command": "a"}]}})[2][0] == '"actions" にオブジェクトを書く形式'
    assert [s.index for s in pc.parse_actions_ex(["a", ["b"], {"command": "c"}]).steps] == [0, 1, 2]  # 番号は書いた順（エラー表示用）


@pytest.mark.parametrize(
    "data,msg",
    [
        ("x", "最上位"),
        ({"foo": []}, '"actions"'),
        ({"steps": 1}, "配列"),
        ({"actions": None}, "配列"),
        ([], "ステップが1つもありません"),
        ([{"params": {}}], '"command" がありません'),
        ([{"command": "a", "params": [1]}], '"params" はオブジェクト'),
        ([[1, {}]], "コマンド ID"),
        ([[]], "どれかで書いてください"),
        ([3], "どれかで書いてください"),
        ([["a", [1]]], '"params" はオブジェクト'),
        ([""], "空"),
    ],
)
def test_parse_actions_errors(data, msg):
    _, errors = pc.parse_actions(data)
    assert any(msg in e for e in errors), errors


def test_grade_recipe_parses(repo_root):
    steps, errors = pc.parse_actions(json.loads((repo_root / "actions/grade.json").read_text(encoding="utf-8")))
    assert errors == [] and len(steps) == 2


def test_param_keys():
    assert pc.param_keys('{"amount":1..500=100,"radius":0.1..64=1,"reduceNoise":0..100=10}') == {"amount", "radius", "reduceNoise"}
    assert pc.param_keys("{}") == set()
    assert pc.param_keys("") is None


def test_registry_from_snapshot(repo_root):
    reg = pc.parse_registry((repo_root / "docs/upstream-snapshot/v0.2.0/generated/commands.json").read_text(encoding="utf-8"))
    assert len(reg) == 748
    c = reg["filter.sharpen.smartSharpen"]
    assert c.menu == "Filter > Sharpen"
    assert pc.param_keys(c.params_doc) == {"amount", "radius", "reduceNoise"}


@pytest.mark.parametrize(
    "line,kind,a,b",
    [
        ("ok    samples/in/a.png -> samples/out/a.png", "ok", "samples/in/a.png", "samples/out/a.png"),
        ("FAIL  C:\\in\\a.png: `x.y`: unknown command `x.y`", "fail", "C:\\in\\a.png", "`x.y`: unknown command `x.y`"),
        ("3 succeeded, 1 failed", "summary", "3", "1"),
        ("warning: 2 layer(s) flattened", "warning", "2 layer(s) flattened", ""),
        ("error: 1 file(s) failed", "error", "1 file(s) failed", ""),
        ("photocraft-cli 0.2.0", "other", "photocraft-cli 0.2.0", ""),
    ],
)
def test_parse_batch_line(line, kind, a, b):
    assert pc.parse_batch_line(line + "\r\n") == pc.BatchLine(kind, a, b)


def test_list_inputs_and_output_name(tmp_path):
    for n in ["b.PNG", "a.psd", "c.txt", "d.avif", ".hidden"]:
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "e.png").write_bytes(b"x")
    assert [p.name for p in pc.list_inputs(tmp_path)] == ["a.psd", "b.PNG"]
    assert pc.list_inputs(tmp_path / "missing") == []
    assert pc.output_name(Path("x/b.PNG")) == "b.PNG"
    assert pc.output_name(Path("x/a.psd"), "png") == "a.png"
