# craft-automation

Craft 系ツール（まず [PhotoCraft](https://github.com/storytold/photocraft)）の CLI / MCP を使った画像処理の自動化リポジトリ。

## 目的
- アクションリスト（JSON）を資産として蓄積・再利用する
- `batch` によるフォルダ単位の一括処理を再現可能にする
- MCP 経由でエージェント（Claude 等）から編集を操作する検証環境を持つ

## アプリ（ブラウザ画面で使う）
Python 3.10 以上を入れたうえで、macOS は `run-app.command`、Windows は `run-app.bat` をダブルクリックする。レシピ管理・一括実行・PhotoCraft の導入、スモークテスト（ピン版と最新版の比較）、本家の更新の確認と Issue 起票、ピン更新の手順、MCP 接続、コマンド台帳を画面で行える。詳しくは [docs/app.md](docs/app.md)。

## 構成
```
craft-automation/
├── app/        # Streamlit アプリ（app/craft_app/ が PhotoCraft アダプタ層）
├── tests/      # アプリのテスト（pytest）
├── run-app.command / run-app.bat  # アプリの起動（macOS / Windows）
├── actions/    # アクションリスト（JSON）。1ファイル=1レシピ
├── scripts/    # CLI ラッパー（batch 実行・前後処理）
├── mcp/        # MCP クライアント設定・検証メモ
├── samples/
│   ├── smoke/  # スモークテスト用の最小入力（コミット対象）
│   ├── in/     # 入力サンプル（git管理外）
│   └── out/    # 出力（git管理外）
├── .github/workflows/  # upstream-watch / smoke / app
├── .upstream/          # 本家の監視対象リスト・記録SHA
├── .photocraft-version # 検証済み本家バージョン（ピン）
└── docs/       # 追跡設計・コマンド一覧・アップグレード履歴
    └── upstream-snapshot/<tag>/  # 版ごとの本家資料（scripts/snapshot-upstream.sh で生成）
```

## 前提
- PhotoCraft は early alpha。API・コマンド名は変更される可能性あり
- リリースのバイナリ、または `cargo run --release -p photocraft`（Rust 1.90+）

## 使い方（PhotoCraft README 記載のコマンド）
```bash
# 単発のヘッドレス編集
photocraft-cli run in.psd \
  --cmd filter.sharpen.smartSharpen --params '{"amount":80}' \
  --out out.png

# アクションリストをフォルダに一括適用
photocraft-cli batch --actions actions/grade.json --in samples/in --out samples/out

# MCP サーバーとして起動
photocraft-cli mcp
```

## 本家更新の追跡
毎日、本家の新リリースと主要文書の更新を検知して Issue 化し、pinned / latest の両方でレシピを実行して破壊的変更を検知する。詳細は [docs/upstream-tracking.md](docs/upstream-tracking.md)。

## アプリ化
要件定義は [docs/requirements.md](docs/requirements.md)、技術選定は [docs/adr/0001-app-stack.md](docs/adr/0001-app-stack.md)。エージェントに渡すファイルは [docs/context-files.txt](docs/context-files.txt)。

## 検証TODO
- [x] 本家 `docs/control-protocol.md` を読み、利用可能なコマンドを `docs/commands.md` に整理（全件は `photocraft-cli commands --json`）
- [x] アクションリストの JSON 形式を確定し、`actions/` に最初のレシピを追加（`actions/grade.json`）
- [x] `photocraft-cli mcp` の公開ツール範囲を確認（`mcp/README.md`）
- [ ] `photocraft-cli mcp` を Claude から接続して操作を確認
- [ ] 日本語テキスト描画の対応状況を確認

## 参考
- PhotoCraft: https://github.com/storytold/photocraft
- 本家 AGENTS.md / docs/roadmap.md / docs/parity.md
