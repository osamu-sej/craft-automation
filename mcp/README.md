# MCP 検証

- 起動: `photocraft-cli mcp`（ヘッドレス）/ `photocraft-cli mcp --bridge 127.0.0.1:<port> --control-token-file <path>`（起動中アプリへのブリッジ）
- 結果は `../docs/` に記録。ツール定義の正本は `../docs/upstream-snapshot/<tag>/generated/mcp-tools.json`

## 確認結果（2026-10-05, v0.1.1 / v0.2.0 の Linux 版で実機確認）
- プロトコル: stdio の MCP（rmcp）。`initialize` 応答は `serverInfo {name: "photocraft", version: "<版>"}`、protocolVersion `2025-06-18`
- 公開ツール 18 個（v0.1.1 と v0.2.0 で同じ）:
  - 常時: `command_list` `command_run` `command_batch` `doc_new` `doc_open` `doc_inspect` `doc_save` `doc_export` `doc_render_preview` `session_list`
  - ヘッドレスのみ: `doc_select` `doc_close`
  - ブリッジのみ: `ui_inspect` `ui_screenshot` `ui_pointer` `ui_menu_invoke` `ui_set` `control_call`（ヘッドレスでは説明付きのエラー）
- `command_batch` は1回最大 256 ステップ

## 認証・ファイルアクセス（v0.2.0 で破壊的変更）
| 項目 | v0.1.1 | v0.2.0 |
|---|---|---|
| ヘッドレスのファイルパス | 絶対パス可 | **ルート指定必須**。`--automation-read-root` / `--automation-write-root` 配下の相対パスのみ。絶対パス・`..` は拒否（`automation path rejected: absolute paths are not allowed`） |
| ブリッジ認証 | なし（制御ポートは無認証） | 64桁16進のトークン。`--control-token-file`（推奨）/ `--control-token` / 環境変数 `PHOTOCRAFT_CONTROL_TOKEN(_FILE)` |

- アプリ側は `photocraft --control <port> --control-token-file <path>` で起動。ファイルが無ければ 256bit トークンを生成し 0600 で保存
- トークンはコミット・ログ出力しない。コマンドラインに直接書かない（`ps` で見える）
- 通信は平文。loopback のみで使う

## クライアント設定例（Claude Code / Claude Desktop、ヘッドレス）
```json
{
  "mcpServers": {
    "photocraft": {
      "command": "/path/to/photocraft-cli",
      "args": ["mcp",
               "--automation-read-root", "/path/to/craft-automation/samples",
               "--automation-write-root", "/path/to/craft-automation/samples/out"]
    }
  }
}
```
ツールに渡すパスはルートからの相対パス（例: `doc_open {"path": "in/a.png"}`）。v0.1.1 はこのオプションを黙って無視し、相対パスをカレントディレクトリ基準で解決するため、同じ設定でも挙動が変わる（v0.2.0 以降専用として扱う）。

## アプリでの確認（実機: v0.2.0 / Linux）
- 「MCP 接続」画面の接続テストで、`photocraft-cli mcp` を起動して initialize → tools/list を行い、18 ツールを確認した（保存: `mcp/tools-v0.2.0.json`）
- **ルートのフォルダが無いと起動に失敗する**: `error: I/O: cannot open automation write root <パス>: No such file or directory`。読み取り・書き出しルートは先に作る（画面に「ルートのフォルダを作る」がある）
- **ブリッジの `mcp` はルートを使わない**（`--bridge` のときは `--automation-*-root` を読まない。本家 `lib.rs` の `mcp`）。ルートは起動中アプリの `photocraft --control … --automation-read-root … --automation-write-root …` に渡す
- ブリッジのトークンファイルが無いと `error: I/O: <パス>: No such file or directory` で終了する（アプリが先に起動してファイルを作る）

## 未検証
- ブリッジモードの正常系（GUI アプリ起動が必要。Linux コンテナでは未実施。異常系 = アプリ未起動は確認済み）
- 日本語テキスト描画（`type.*` 系コマンド）
