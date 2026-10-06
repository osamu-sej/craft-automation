"""MCP 接続支援（requirements.md FR-07）。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import streamlit as st

from craft_app import mcp, photocraft
from craft_app.paths import app_data_dir

from . import common


def render() -> None:
    st.title("MCP 接続")
    common.show_flash("mcp")
    st.caption("Claude などの MCP クライアントが `photocraft-cli mcp` を起動して PhotoCraft を操作できるよう、設定を作って接続を確かめます。"
               "MCP は標準入出力で話すので、サーバーはクライアントが起動します。ここでは同じ引数で一度起動し、応答を確かめてから止めます。")
    repo = common.repo()
    inst = common.current()
    if inst is None:
        st.warning("PhotoCraft が未導入です。「バージョン」ページで導入してください。")
        return

    mode = st.radio("モード", ["ヘッドレス（ウィンドウなし）", "ブリッジ（起動中の PhotoCraft アプリを操作）"], horizontal=True, key="mcp_mode")
    bridge = mode.startswith("ブリッジ")
    roots = photocraft.supports_automation_roots(inst.tag)

    read_root = write_root = bridge_addr = token_file = None
    errors: list[str] = []
    if bridge:
        c = st.columns(2)
        bridge_addr = c[0].text_input("ブリッジ先", "127.0.0.1:7878", key="mcp_bridge", help="`photocraft --control <ポート> --control-token-file <ファイル>` で起動したアプリのアドレス。loopback のみ")
        token_file = c[1].text_input("トークンファイル", str(app_data_dir() / "photocraft-control.token"), key="mcp_token",
                                     help="アプリ側とクライアント側で同じファイルを指定します。ファイルが無ければアプリが 256bit のトークンを作ります。トークンの値は設定に書きません")
        if (msg := mcp.check_bridge_addr(bridge_addr)) is not None:
            errors.append(msg)
    if roots:
        c = st.columns(2)
        read_text = c[0].text_input("読み取りルート", str(repo.root / "samples"), key="mcp_read",
                                    help="MCP から開けるフォルダ。パスはこのフォルダからの相対パスだけ（絶対パスと .. は拒否されます）")
        write_text = c[1].text_input("書き出しルート", str(repo.root / "samples" / "out"), key="mcp_write",
                                     help="MCP から保存できるフォルダ。保存先の親フォルダは先に作っておく必要があります")
        read_root, write_root = repo.resolve(read_text), repo.resolve(write_text)
        missing = [(n, r) for n, r in (("読み取りルート", read_root), ("書き出しルート", write_root)) if mcp.check_root(r)]
        for n, r in missing:
            errors.append(f"{n}の{mcp.check_root(r)}")
        if missing and st.button("ルートのフォルダを作る", icon=":material/create_new_folder:"):
            try:
                for _, r in missing:
                    r.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                st.error(f"作れませんでした: {e}")
            else:
                st.rerun()
    else:
        st.warning(f"{inst.tag} は `--automation-read-root` / `--automation-write-root` を持ちません（v0.2.0 で追加）。"
                   "オプションは黙って無視され、絶対パスでファイルを開けてしまいます。v0.2.0 以降での利用を勧めます。")

    # ブリッジの `mcp` はルートを使わない（本家 lib.rs の mcp）。ルートは起動中のアプリ側に渡す
    args = mcp.server_args(bridge=bridge_addr if bridge else None, read_root=None if bridge else read_root,
                           write_root=None if bridge else write_root, token_file=token_file if bridge else None)
    if bridge and not errors:
        st.subheader("先にアプリを起動する")
        app_cmd = f'photocraft --control {bridge_addr.rsplit(":", 1)[-1]} --control-token-file "{token_file}"'
        if roots:
            app_cmd += f' --automation-read-root "{read_root}" --automation-write-root "{write_root}"'
        st.code(app_cmd, language=None, wrap_lines=True)
        if not Path(token_file).is_file():
            st.info("トークンファイルがまだありません。上のコマンドでアプリを一度起動すると、アプリが作ります（作る前に接続テストをすると失敗します）。")
        st.caption("ファイルの読み書きできるフォルダは、アプリの起動時に決まります（MCP 側のオプションでは変えられません）。トークンファイルは自分だけが読める場所に置いてください。")
    st.subheader("クライアントの設定")
    st.markdown("**Claude Desktop / Claude Code**（`mcpServers` に追加。`claude_desktop_config.json` や `.mcp.json`）")
    st.code(mcp.client_json(inst.cli, args), language="json")
    st.markdown("**Claude Code**（コマンドで登録する場合）")
    st.code(mcp.claude_code_command(inst.cli, args, windows=os.name == "nt"), language="bash" if os.name != "nt" else None)
    st.caption("ツールに渡すパスは、読み取り・書き出しルートからの相対パスです（例: `doc_open {\"path\": \"in/a.png\"}`）。")

    st.subheader("接続テスト")
    for e in errors:
        st.error(e)
    if st.button("起動して確かめる", type="primary", disabled=bool(errors), icon=":material/power:"):
        with st.spinner("`photocraft-cli mcp` を起動しています…"):
            try:
                res = mcp.probe(inst.cli, args, timeout=30)
            except mcp.ProbeError as e:
                st.session_state["mcp_result"] = ("error", str(e), None, inst.tag, bridge)
            else:
                st.session_state["mcp_result"] = ("ok", "", res, inst.tag, bridge)
        st.rerun()

    got = st.session_state.get("mcp_result")
    if got:
        status, msg, res, tag, was_bridge = got
        if status == "error":
            st.error(f"接続できませんでした（{tag}、{'ブリッジ' if was_bridge else 'ヘッドレス'}）:\n\n{msg}")
            if was_bridge:
                st.caption("ブリッジはアプリが `--control` で起動している必要があります。上のコマンドで起動してから、もう一度試してください。")
        else:
            st.success(f"起動できました: {res.server} {res.version}（MCP {res.protocol}）。公開ツール {len(res.tools)} 個。サーバーは止めました")
            st.dataframe([{"ツール": t["name"], "説明": (t.get("description") or "").split("\n")[0]} for t in res.tools], hide_index=True, width="stretch")
            _save(res, tag, repo.root)


def _save(res: mcp.Probe, tag: str, root) -> None:
    saved = mcp.saved_tools(root)
    path = mcp.tools_path(root, tag)
    same = tag in saved and saved[tag] == res.tools
    if st.button(f"ツール一覧を保存（{common.rel(path)}）", disabled=same, icon=":material/save:"):
        mcp.save_tools(root, tag, res.tools)
        common.flash("mcp", "success", f"{common.rel(path)} に保存しました（コミットして共有してください）")
        st.rerun()
    if same:
        st.caption("保存済みの一覧と同じです")
    others = {t: v for t, v in saved.items() if t != tag}
    if others:
        prev = max(others, key=lambda t: photocraft_key(t))
        d = mcp.diff_tools(others[prev], res.tools)
        if any(d.values()):
            st.warning(f"保存済みの {prev} との違い — 追加: {', '.join(d['added']) or 'なし'} / 削除: {', '.join(d['removed']) or 'なし'} / 定義が変更: {', '.join(d['changed']) or 'なし'}")
        else:
            st.caption(f"保存済みの {prev} と同じツール一覧です")


def photocraft_key(tag: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", tag)[:3])
