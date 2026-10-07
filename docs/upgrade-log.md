# アップグレード履歴

| 日付 | from | to | 結果 | 修正内容 |
|---|---|---|---|---|
| 2026-10-05 | - | v0.1.1 | 初期ピン | リポジトリ作成 |
| 2026-10-05 | v0.1.1 | v0.2.0 | smoke 両版成功（grade）。CLI 互換、MCP は破壊的変更 | MCP のファイルアクセスにルート指定が必須に（`mcp/README.md`）。スナップショット `docs/upstream-snapshot/v0.2.0/` |
| 2026-10-07 | v0.2.0 | v0.3.0 | smoke 両版成功（grade）、出力は同一（SHA256 一致）。CLI は互換。コマンド 748→776（追加のみ、使用中の 2 件の書式は不変）。MCP は追加のみ（18→20: jobs_list・jobs_cancel） | batch の新書式・Windows ARM64 ネイティブ版・同名出力の失敗に対応（アダプタ）。監視対象に crates/engine/src/automate_cmds.rs を追加。スナップショット docs/upstream-snapshot/v0.3.0/ |
