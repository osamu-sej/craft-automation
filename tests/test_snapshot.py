import http.server
import json
import sys
import threading
from functools import partial

import pytest

from conftest import write_mock_cli
from craft_app import mcp, photocraft as pc, releases, snapshot

TAG = "v9.9.9"


@pytest.fixture
def server(tmp_path, monkeypatch):
    """本家の raw ファイルとリリースの代わりをするローカル HTTP サーバー。"""
    root = tmp_path / "srv"
    for f in snapshot.FILES:
        p = root / "raw" / TAG / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"# {f}\n日本語 ✓\n".encode("utf-8"))
    rel = root / "rel" / TAG
    rel.mkdir(parents=True)
    (rel / "SHA256SUMS.txt").write_text("abc  photocraft-9.9.9-linux-x86_64.tar.gz\n", encoding="utf-8")
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    monkeypatch.setattr(snapshot, "RAW", f"{base}/raw")
    monkeypatch.setattr(pc, "RELEASE_DOWNLOAD", f"{base}/rel")
    monkeypatch.setattr(snapshot, "commit_sha", lambda tag: "c" * 40)
    yield root
    httpd.shutdown()


def test_create_writes_everything_the_shell_script_does(server, tmp_path):
    cli = write_mock_cli(tmp_path / "bin/photocraft-cli")
    out = snapshot.create(TAG, cli, tmp_path / "snap")
    assert out == tmp_path / "snap" / TAG
    for f in snapshot.FILES:
        assert (out / f).read_bytes() == f"# {f}\n日本語 ✓\n".encode("utf-8")  # バイト単位で同じ
    g = out / "generated"
    assert (g / "version.txt").read_text(encoding="utf-8") == "photocraft-cli 9.9.9 (mock, 2026-01-01)\n"
    assert (g / "release-assets.txt").read_text(encoding="utf-8").startswith("abc  photocraft-9.9.9")
    assert len(json.loads((g / "commands.json").read_text(encoding="utf-8"))) == 748
    assert [t["name"] for t in json.loads((g / "mcp-tools.json").read_text(encoding="utf-8"))] == ["command_run", "doc_open"]
    src = (out / "SOURCE.md").read_text(encoding="utf-8")
    assert f"commit `{'c' * 40}`" in src and src.startswith(f"# 本家スナップショット {TAG}")
    assert not list((tmp_path / "snap").glob(".*partial"))


def test_rebuild_replaces_and_failure_keeps_the_old_one(server, tmp_path):
    cli = write_mock_cli(tmp_path / "bin/photocraft-cli")
    out = snapshot.create(TAG, cli, tmp_path / "snap")
    (out / "stale.txt").write_text("古い", encoding="utf-8")
    snapshot.create(TAG, cli, tmp_path / "snap")
    assert not (out / "stale.txt").exists()  # 毎回作り直す（版の混在を防ぐ）
    (server / "raw" / TAG / "NOTICE").unlink()  # 本家側にファイルがない
    (out / "keep.txt").write_text("残る", encoding="utf-8")
    with pytest.raises(releases.DownloadError) as e:
        snapshot.create(TAG, cli, tmp_path / "snap")
    assert e.value.status == 404 and e.value.url.endswith("/NOTICE")
    assert (out / "keep.txt").exists()  # 失敗したら既存はそのまま
    assert not list((tmp_path / "snap").glob(".*partial"))


@pytest.mark.integration
def test_matches_the_committed_snapshot_of_v0_2_0(tmp_path, repo_root):
    """Python 版が、シェル版で作ってコミット済みの v0.2.0 スナップショットと同じ内容を作る。"""
    inst = releases.install("v0.2.0", tmp_path / "bin")
    out = snapshot.create("v0.2.0", inst.cli, tmp_path / "snap")
    committed = repo_root / "docs/upstream-snapshot/v0.2.0"
    norm = lambda p: p.read_bytes().replace(b"\r\n", b"\n")  # noqa: E731 - Windows の改行変換を無視する
    # OS に依らない内容は、バイト単位で同じ
    for f in [*snapshot.FILES, "generated/release-assets.txt", "SOURCE.md"]:
        assert norm(out / f) == norm(committed / f), f
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    assert load(out / "generated/mcp-tools.json") == load(committed / "generated/mcp-tools.json")
    ids = lambda d: sorted(c["id"] for c in load(d / "generated/commands.json"))  # noqa: E731
    assert ids(out) == ids(committed) and len(ids(out)) == 748
    if sys.platform == "linux":
        # コミット済みは Linux 版で作った。他 OS の本家バイナリが同じ出力かは未確認なので、Linux だけ厳密に比べる
        for f in ["generated/version.txt", "generated/commands.json"]:
            assert norm(out / f) == norm(committed / f), f
