"""photocraft-cli batch の振る舞いを真似るモック（tests 専用）。

コマンド "fail.me" を含むレシピは各ファイルで失敗し、"slow" は 30 秒待つ（キャンセル確認用）。
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

EXTS = {"png", "jpg", "psd"}


TOOLS = [
    {"name": "doc_open", "description": "Open a document", "inputSchema": {"type": "object"}},
    {"name": "command_run", "description": "Run a command", "inputSchema": {"type": "object"}},
]


def mcp(argv):
    """photocraft-cli mcp の真似。stdin の JSON-RPC 行に答える。--bridge はアプリがない想定で失敗する。"""
    if "--bridge" in argv:
        print("error: bridge connect 127.0.0.1: connection refused", file=sys.stderr)
        return 1
    if os.environ.get("MOCK_MCP_LATE_EXIT") == "1":
        # 標準出力を先に閉じ、少ししてから失敗終了する（EOF の時点ではまだ終了コードが取れない）
        print("error: late failure", file=sys.stderr, flush=True)
        os.close(1)
        time.sleep(1.0)
        return 3
    if os.environ.get("MOCK_MCP_HANG") == "1":
        time.sleep(60)
        return 0
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            out = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "photocraft", "version": "9.9.9"}, "capabilities": {}}
        elif msg.get("method") == "tools/list":
            out = {"tools": TOOLS}
        else:
            continue  # notifications には返さない
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": out}), flush=True)
    return 0


def main(argv):
    # 本物の CLI と同じく UTF-8 で出す（Windows の既定は cp1252 など）
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if argv[:1] == ["--version"]:
        print("photocraft-cli 9.9.9 (mock, 2026-01-01)")
        return 0
    if argv[:2] == ["commands", "--json"]:
        snap = Path(__file__).resolve().parents[1] / "docs/upstream-snapshot/v0.2.0/generated/commands.json"
        sys.stdout.write(snap.read_text(encoding="utf-8"))
        sys.stdout.flush()
        return 0
    if argv[:1] == ["mcp"]:
        return mcp(argv[1:])
    if argv[:1] != ["batch"]:
        print(f"error: unknown command `{argv[:1]}`", file=sys.stderr)
        return 2
    opts = dict(zip(argv[1::2], argv[2::2]))
    data = json.loads(Path(opts["--actions"]).read_text(encoding="utf-8"))
    actions = data["actions"] if isinstance(data, dict) else data
    cmds = [a.get("command", a.get("id")) for a in actions]
    if os.environ.get("MOCK_FAIL") == "1":  # 破壊的変更の入った版のふり
        cmds.append("fail.me")
    out = Path(opts["--out"])
    out.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for p in sorted(Path(opts["--in"]).iterdir()):
        if not p.is_file() or p.suffix[1:].lower() not in EXTS:
            continue
        if "slow" in cmds:
            time.sleep(30)
        if "fail.me" in cmds:
            print(f"FAIL  {p}: `fail.me`: unknown command `fail.me`", file=sys.stderr, flush=True)
            failed += 1
            continue
        ext = opts.get("--format") or p.suffix[1:]
        target = out / f"{p.stem}.{ext}"
        shutil.copyfile(p, target)
        ok += 1
        print(f"ok    {p} -> {target}", flush=True)
        print("warning: 2 layer(s) flattened; layers, masks and blend modes are not kept", file=sys.stderr, flush=True)
    print(f"{ok} succeeded, {failed} failed", flush=True)
    if failed:
        print(f"error: {failed} file(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
