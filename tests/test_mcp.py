import json
import shutil

import pytest

from conftest import write_mock_cli
from craft_app import mcp
from craft_app import photocraft as pc
from craft_app import releases


def test_headless_args_and_snippets():
    args = mcp.server_args(read_root="/r/samples", write_root="/r/samples/out")
    assert args == ["mcp", "--automation-read-root", "/r/samples", "--automation-write-root", "/r/samples/out"]
    data = json.loads(mcp.client_json("/bin/photocraft-cli", args))
    assert data == {"mcpServers": {"photocraft": {"command": "/bin/photocraft-cli", "args": args}}}
    cmd = mcp.claude_code_command("/my dir/photocraft-cli", args)
    assert cmd.startswith("claude mcp add photocraft -- '/my dir/photocraft-cli' mcp --automation-read-root /r/samples")
    win = mcp.claude_code_command(r"C:\Program Files\pc\photocraft-cli.exe", ["mcp"], windows=True)
    assert win == 'claude mcp add photocraft -- "C:\\Program Files\\pc\\photocraft-cli.exe" mcp'


def test_bridge_uses_token_file_never_a_token_value():
    args = mcp.server_args(bridge="127.0.0.1:7878", token_file="/p/photocraft-control.token")
    assert args == ["mcp", "--bridge", "127.0.0.1:7878", "--control-token-file", "/p/photocraft-control.token"]
    assert "--control-token" not in args  # 値を直接渡す形（ps で見える）は作らない


@pytest.mark.parametrize("addr,ok", [("127.0.0.1:7878", True), ("127.0.0.1:1", True), ("127.0.0.1:0", False), ("127.0.0.1:70000", False),
                                     ("0.0.0.0:7878", False), ("example.com:7878", False), ("127.0.0.1", False), ("localhost:7878", False)])
def test_bridge_addr_is_loopback_only(addr, ok):
    assert (mcp.check_bridge_addr(addr) is None) == ok


def test_roots_supported_from_v020():
    assert [pc.supports_automation_roots(t) for t in ["v0.1.0", "v0.1.1", "v0.1.1-rc.5", "v0.2.0", "v0.2.1", "v1.0.0", "nightly"]] == [
        False, False, False, True, True, True, False]


def test_probe_lists_tools(tmp_path):
    cli = write_mock_cli(tmp_path / "photocraft-cli")
    p = mcp.probe(cli, mcp.server_args(read_root="r"))
    assert (p.server, p.version, p.protocol) == ("photocraft", "9.9.9", "2025-06-18")
    assert p.tool_names == ["command_run", "doc_open"]  # 名前順


def test_probe_reports_exit_and_stderr(tmp_path):
    cli = write_mock_cli(tmp_path / "photocraft-cli")
    with pytest.raises(mcp.ProbeError) as e:
        mcp.probe(cli, mcp.server_args(bridge="127.0.0.1:7878", token_file="t"))
    assert "終了コード 1" in str(e.value) and "connection refused" in str(e.value)


def test_probe_times_out_and_stops_the_server(tmp_path):
    cli = write_mock_cli(tmp_path / "photocraft-cli", env={"MOCK_MCP_HANG": "1"})
    with pytest.raises(mcp.ProbeError, match="応答がありません"):
        mcp.probe(cli, ["mcp"], timeout=1)


def test_probe_missing_binary(tmp_path):
    with pytest.raises(mcp.ProbeError, match="起動できません"):
        mcp.probe(tmp_path / "nope", ["mcp"])


def test_save_and_diff_tools(tmp_path):
    a = [{"name": "b", "description": "1"}, {"name": "a", "description": "x"}]
    path = mcp.save_tools(tmp_path, "v0.2.0", a)
    assert path == tmp_path / "mcp" / "tools-v0.2.0.json"
    assert [t["name"] for t in json.loads(path.read_text(encoding="utf-8"))] == ["a", "b"]
    assert mcp.saved_tools(tmp_path) == {"v0.2.0": sorted(a, key=lambda t: t["name"])}
    new = [{"name": "a", "description": "changed"}, {"name": "c", "description": ""}]
    assert mcp.diff_tools(a, new) == {"added": ["c"], "removed": ["b"], "changed": ["a"]}


@pytest.mark.integration
def test_real_release_exposes_the_documented_tools(tmp_path, repo_root):
    """本家 v0.2.0 を実際に起動してハンドシェイクし、保存済みスナップショットと同じ 18 ツールが出ること。"""
    inst = releases.install("v0.2.0", tmp_path / "bin")
    (tmp_path / "r").mkdir()
    p = mcp.probe(inst.cli, mcp.server_args(read_root=tmp_path / "r", write_root=tmp_path / "r"), timeout=60)
    snap = json.loads((repo_root / "docs/upstream-snapshot/v0.2.0/generated/mcp-tools.json").read_text(encoding="utf-8"))
    assert (p.server, p.version) == ("photocraft", "0.2.0")
    assert p.tool_names == [t["name"] for t in snap] and len(p.tools) == 18
    assert mcp.diff_tools(snap, p.tools) == {"added": [], "removed": [], "changed": []}


def test_check_root(tmp_path):
    assert mcp.check_root(tmp_path) is None
    assert "フォルダがありません" in mcp.check_root(tmp_path / "nope")
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert "フォルダではありません" in mcp.check_root(f)


@pytest.mark.integration
def test_real_release_fails_without_the_root_folder(tmp_path):
    """画面で先に止める理由: 本家はルートのフォルダが無いと、実際に起動に失敗する。"""
    inst = releases.install("v0.2.0", tmp_path / "bin")
    with pytest.raises(mcp.ProbeError, match="cannot open automation write root"):
        mcp.probe(inst.cli, mcp.server_args(read_root=tmp_path, write_root=tmp_path / "missing"), timeout=60)
