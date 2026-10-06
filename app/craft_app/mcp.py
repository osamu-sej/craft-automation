"""MCP 接続支援（requirements.md FR-07）。

`photocraft-cli mcp` は stdio で話す MCP サーバーで、Claude などのクライアントが自分で起動する。
アプリの役割は、(1) クライアントに貼る設定を作る、(2) 同じ引数で起動して「起動できる・ツール一覧が取れる」
ことを確かめて止める（接続テスト）、(3) ツール一覧を保存する、の 3 つ。

本家の仕様（docs/control-protocol.md, v0.2.0）:
- ヘッドレス: `photocraft-cli mcp`。ファイルを扱うには `--automation-read-root` / `--automation-write-root` が必須（相対パスのみ）
- ブリッジ: `photocraft-cli mcp --bridge 127.0.0.1:<port> --control-token-file <path>`（起動中のアプリ `photocraft --control <port> ...` へ）
- トークンは設定に埋め込まない。ファイル（`--control-token-file`）で渡す
"""

from __future__ import annotations

import json
import queue
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import jobs, photocraft

PROTOCOL = "2025-06-18"
_LOOPBACK = re.compile(r"^127\.0\.0\.1:(\d{1,5})$")


def check_bridge_addr(addr: str) -> str | None:
    """ブリッジ先として使えなければ理由を返す（本家は loopback だけを受け付ける）。"""
    m = _LOOPBACK.match(addr.strip())
    if not m:
        return "127.0.0.1:<ポート> の形で指定してください（本家のブリッジは loopback のみ）"
    if not 1 <= int(m[1]) <= 65535:
        return "ポートは 1〜65535 です"
    return None


def check_root(path: Path) -> str | None:
    """MCP のルート（読み取り・書き出し）として使えなければ理由を返す。

    本家 v0.2.0 は、ルートのフォルダが無いと `cannot open automation read/write root` で起動に失敗する。
    """
    if path.is_dir():
        return None
    if path.exists():
        return f"フォルダではありません: {path}"
    return f"フォルダがありません: {path}"


def server_args(*, bridge: str | None = None, read_root: Path | str | None = None,
                write_root: Path | str | None = None, token_file: Path | str | None = None) -> list[str]:
    """`photocraft-cli` に渡す引数（先頭の `mcp` から）。"""
    args = ["mcp"]
    if bridge:
        args += ["--bridge", bridge.strip()]
        if token_file:
            args += ["--control-token-file", str(token_file)]
    if read_root:
        args += ["--automation-read-root", str(read_root)]
    if write_root:
        args += ["--automation-write-root", str(write_root)]
    return args


def client_json(cli: Path | str, args: list[str], name: str = "photocraft") -> str:
    """Claude Desktop / Claude Code の `mcpServers` に入れる設定。"""
    return json.dumps({"mcpServers": {name: {"command": str(cli), "args": args}}}, ensure_ascii=False, indent=2) + "\n"


def claude_code_command(cli: Path | str, args: list[str], name: str = "photocraft", windows: bool = False) -> str:
    """Claude Code に登録するコマンド（`claude mcp add`）。"""
    words = [str(cli), *args]
    quoted = subprocess.list2cmdline(words) if windows else shlex.join(words)
    return f"claude mcp add {name} -- {quoted}"


# ---- 接続テスト --------------------------------------------------------------------


class ProbeError(RuntimeError):
    pass


@dataclass
class Probe:
    server: str
    version: str
    protocol: str
    tools: list[dict] = field(default_factory=list)
    stderr: str = ""

    @property
    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.tools]


def probe(cli: Path | str, args: list[str], timeout: float = 30) -> Probe:
    """MCP サーバーを起動し、initialize → tools/list を 1 往復して止める。

    起動できない・時間内に答えない・途中で終了した場合は、終了コードと標準エラーを付けた ProbeError にする。
    """
    cmd = [str(cli), *args]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise ProbeError(f"起動できません: {e}") from e
    lines: queue.Queue[str | None] = queue.Queue()
    err: list[str] = []

    def pump_out() -> None:
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)

    t_out = threading.Thread(target=pump_out, daemon=True)
    t_err = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)
    t_out.start()
    t_err.start()

    def fail(msg: str) -> ProbeError:
        jobs.kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        t_err.join(timeout=2)  # 終了直前に出た標準エラーも読み切ってから、メッセージにする
        text = "".join(err).strip()
        return ProbeError(f"{msg}" + (f"\n{text}" if text else ""))

    def send(obj: dict) -> None:
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
        except OSError as e:
            raise fail(f"サーバーへ送れません: {e}") from e

    def reply(want: int) -> dict:
        while True:
            try:
                ln = lines.get(timeout=timeout)
            except queue.Empty:
                raise fail(f"{timeout:g} 秒以内に応答がありません") from None
            if ln is None:
                # 標準出力が閉じた直後は、まだ終了コードを回収できていないことがある（Windows で実際に起きた）
                try:
                    code = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    code = proc.poll()
                raise fail(f"サーバーが終了しました（終了コード {code}）")
            try:
                msg = json.loads(ln)
            except ValueError:
                continue  # JSON 以外の行は無視する
            if msg.get("id") == want:
                if "error" in msg:
                    raise fail(f"サーバーがエラーを返しました: {msg['error']}")
                return msg["result"]

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "craft-automation", "version": "0"}}})
        init = reply(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = sorted(reply(2).get("tools", []), key=lambda t: t["name"])
        info = init.get("serverInfo", {})
        return Probe(info.get("name", ""), info.get("version", ""), init.get("protocolVersion", ""), tools, "".join(err).strip())
    finally:
        if proc.poll() is None:
            jobs.kill_tree(proc)
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


# ---- ツール一覧の保存と比較 -----------------------------------------------------------


def tools_path(root: Path, tag: str) -> Path:
    return root / "mcp" / f"tools-{tag}.json"


def save_tools(root: Path, tag: str, tools: list[dict]) -> Path:
    p = tools_path(root, tag)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(tools, key=lambda t: t["name"]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return p


def saved_tools(root: Path) -> dict[str, list[dict]]:
    """保存済みのツール一覧（版 → ツール）。"""
    out = {}
    for p in sorted((root / "mcp").glob("tools-*.json")) if (root / "mcp").is_dir() else []:
        try:
            out[p.stem[len("tools-"):]] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return out


def diff_tools(old: list[dict], new: list[dict]) -> dict[str, list[str]]:
    """ツール名の追加・削除と、説明や入力定義が変わったもの。"""
    o, n = {t["name"]: t for t in old}, {t["name"]: t for t in new}
    return {
        "added": sorted(set(n) - set(o)),
        "removed": sorted(set(o) - set(n)),
        "changed": sorted(k for k in set(o) & set(n) if o[k] != n[k]),
    }
