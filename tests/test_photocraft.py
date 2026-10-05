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


@pytest.mark.parametrize(
    "data",
    [
        [{"command": "a.b", "params": {"x": 1}}, {"id": "c.d"}],
        {"tested_with": "v0.2.0", "actions": [{"command": "a.b", "params": {"x": 1}}, {"id": "c.d"}]},
    ],
)
def test_parse_actions_forms(data):
    steps, errors = pc.parse_actions(data)
    assert errors == []
    assert [(s.command, s.params) for s in steps] == [("a.b", {"x": 1}), ("c.d", {})]


@pytest.mark.parametrize(
    "data,msg",
    [
        ("x", "最上位"),
        ({"steps": []}, '"actions"'),
        ([], "ステップが1つもありません"),
        ([{"params": {}}], '"command" がありません'),
        ([{"command": "a", "params": [1]}], '"params" はオブジェクト'),
    ],
)
def test_parse_actions_errors(data, msg):
    _, errors = pc.parse_actions(data)
    assert any(msg in e for e in errors)


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
