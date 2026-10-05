import hashlib
import http.server
import io
import os
import tarfile
import threading
import zipfile
from functools import partial

import pytest

from craft_app import photocraft as pc
from craft_app import releases

TAG = "v9.9.9"


def test_version_order():
    tags = ["v0.1.1-rc.4", "v0.2.0", "v0.1.0", "v0.1.1", "v0.1.1-rc.5", "nightly"]
    assert sorted(tags, key=releases._version_key, reverse=True) == ["v0.2.0", "v0.1.1", "v0.1.1-rc.5", "v0.1.1-rc.4", "v0.1.0", "nightly"]


def _archive(asset: pc.Asset, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    if asset.archive == "tar.gz":
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o755
                tf.addfile(info, io.BytesIO(data))
    else:
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def server(tmp_path, monkeypatch):
    """ローカルの HTTP サーバーを本家リリースの代わりにする。"""
    root = tmp_path / "srv"
    (root / TAG).mkdir(parents=True)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(pc, "RELEASE_DOWNLOAD", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setattr(pc, "cli_version", lambda cli, timeout=30: "photocraft-cli 9.9.9")
    yield root / TAG
    httpd.shutdown()


def _publish(d, files, sums_override=None):
    asset = pc.asset_for(TAG)
    data = _archive(asset, files)
    (d / asset.name).write_bytes(data)
    digest = sums_override or hashlib.sha256(data).hexdigest()
    (d / "SHA256SUMS.txt").write_text(f"{digest}  {asset.name}\n", encoding="utf-8")
    return asset


def test_install_verifies_and_extracts(server, tmp_path):
    asset = _publish(server, {pc.asset_for(TAG).cli_relpath: b"#!/bin/sh\necho ok\n"})
    seen = []
    inst = releases.install(TAG, tmp_path / "bin", lambda d, t: seen.append(d))
    assert inst.cli == tmp_path / "bin" / TAG / asset.cli_relpath and inst.cli.is_file()
    if os.name != "nt":
        assert os.access(inst.cli, os.X_OK)  # zip 展開でも実行権限を付ける
    assert seen and [i.tag for i in releases.installed(tmp_path / "bin")] == [TAG]
    assert not (tmp_path / "bin" / TAG / asset.name).exists()  # アーカイブは残さない


def test_checksum_mismatch_leaves_nothing(server, tmp_path):
    _publish(server, {pc.asset_for(TAG).cli_relpath: b"x"}, sums_override="0" * 64)
    with pytest.raises(RuntimeError, match="SHA256"):
        releases.install(TAG, tmp_path / "bin")
    assert releases.installed(tmp_path / "bin") == []
    assert [p.name for p in (tmp_path / "bin").iterdir()] == []


def test_missing_asset_reports_url_and_status(server, tmp_path):
    (server / "SHA256SUMS.txt").write_text("abc  something-else.zip\n", encoding="utf-8")
    with pytest.raises(releases.DownloadError, match="一覧にありません"):
        releases.install(TAG, tmp_path / "bin")
    with pytest.raises(releases.DownloadError) as e:
        releases.install("v0.0.0", tmp_path / "bin")
    assert e.value.status == 404 and e.value.url.endswith("/v0.0.0/SHA256SUMS.txt")


def test_rejects_path_traversal(server, tmp_path):
    _publish(server, {"../evil": b"x", pc.asset_for(TAG).cli_relpath: b"x"})
    with pytest.raises(RuntimeError, match="不正なパス"):
        releases.install(TAG, tmp_path / "bin")
    assert not (tmp_path / "evil").exists()


def test_missing_cli_in_archive(server, tmp_path):
    _publish(server, {"README.md": b"x"})
    with pytest.raises(RuntimeError, match="ありません"):
        releases.install(TAG, tmp_path / "bin")


@pytest.mark.skipif(os.name == "nt", reason="実行権限は POSIX のみ")
def test_macos_zip_gets_exec_bit(server, tmp_path, monkeypatch):
    """macOS 版は zip。zipfile は実行権限を保持しないので展開後に付ける。"""
    monkeypatch.setattr(pc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(pc.platform, "machine", lambda: "arm64")
    asset = _publish(server, {pc.asset_for(TAG).cli_relpath: b"#!/bin/sh\necho ok\n"})
    assert asset.archive == "zip"
    inst = releases.install(TAG, tmp_path / "bin")
    assert os.access(inst.cli, os.X_OK)
