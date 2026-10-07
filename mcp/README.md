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

## v0.3.0 での変化（2026-10-07, Linux 版で実機確認。保存: `tools-v0.3.0.json`）
- 公開ツール 20 個（18 → 20）。追加は `jobs_list` / `jobs_cancel`（長い処理をバックグラウンドジョブにしたため。本家 `docs/control-protocol.md` の「Background jobs」）。削除・改名はなし
- 既存ツールの入力は追加のみ（必須項目は変わらない）: `command_run` と `command_batch` のステップに任意の `wait`（`false` で長い処理をジョブとして始め、`{job, pending}` が先に返る）、`ui_pointer` に任意の `button`
- 説明・制約が変わったもの（保存した一覧どうしの比較）: `doc_save` と `doc_export`（`path` を省くと、PSD・PSB・`.pcraft` だけは元のファイルへ元の形式のまま書き戻す。それ以外は `path` が要る）、`doc_render_preview` と `ui_screenshot`（`max_side` は既定 1024・上限 2048、0 は上限内で原寸）、`ui_inspect`（メニュー木を含まない。`control_call` で `ui.menu.list` を呼ぶ）、`ui_set`（`fields` の項目が増えた）
- 返信・プレビューに上限がついた（返信 8 MiB、ヘッドレスのプレビューは長辺 2048 px・元 67,108,864 px・PNG 5 MiB まで）
- ヘッドレス（`photocraft-cli mcp --automation-read-root … --automation-write-root …`）の起動と、ルートが必須なことは v0.2.0 と同じ。ブリッジの正常系は未検証のまま

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
