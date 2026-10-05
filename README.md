# craft-automation

Craft 系ツール（まず [PhotoCraft](https://github.com/storytold/photocraft)）の CLI / MCP を使った画像処理の自動化リポジトリ。

## 目的
- アクションリスト（JSON）を資産として蓄積・再利用する
- `batch` によるフォルダ単位の一括処理を再現可能にする
- MCP 経由でエージェント（Claude 等）から編集を操作する検証環境を持つ

## 構成
```
craft-automation/
├── actions/    # アクションリスト（JSON）。1ファイル=1レシピ
├── scripts/    # CLI ラッパー（batch 実行・前後処理）
├── mcp/        # MCP クライアント設定・検証メモ
├── samples/
│   ├── smoke/  # スモークテスト用の最小入力（コミット対象）
│   ├── in/     # 入力サンプル（git管理外）
│   └── out/    # 出力（git管理外）
├── .github/workflows/  # upstream-watch / smoke
├── .upstream/          # 本家の監視対象リスト・記録SHA
├── .photocraft-version # 検証済み本家バージョン（ピン）
└── docs/       # 追跡設計・コマンド一覧・アップグレード履歴
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
要件定義は [docs/requirements.md](docs/requirements.md)。エージェントに渡すファイルは [docs/context-files.txt](docs/context-files.txt)。

## 検証TODO
- [ ] 本家 `docs/control-protocol.md` を読み、利用可能なコマンドを `docs/commands.md` に整理
- [ ] アクションリストの JSON 形式を確定し、`actions/` に最初のレシピを追加
- [ ] `photocraft-cli mcp` を Claude から接続し、公開ツール範囲を確認
- [ ] 日本語テキスト描画の対応状況を確認

## 参考
- PhotoCraft: https://github.com/storytold/photocraft
- 本家 AGENTS.md / docs/roadmap.md / docs/parity.md
