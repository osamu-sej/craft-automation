# 本家スナップショット v0.2.0

- 取得元: https://github.com/storytold/photocraft/tree/v0.2.0 （commit `ad863217386440ca968fccc9bfff65ba24e61142`）
- 生成: `scripts/snapshot-upstream.sh v0.2.0` またはアプリの「ピン更新」（手で編集しない）
- ライセンス: 本家は MIT OR Apache-2.0。同梱の LICENSE-MIT / LICENSE-APACHE / NOTICE を参照

| ファイル | 内容 |
|---|---|
| README.md, AGENTS.md, docs/*.md | 本家文書（v0.2.0 時点） |
| apps/photocraft-cli/src/lib.rs | CLI 定義。v0.2.0 までは `parse_actions` が batch のアクションリスト形式の正本 |
| crates/engine/src/automate_cmds.rs | v0.3.0 からのアクションリスト形式の正本（`parse_action` / `parse_steps`） |
| crates/automation/src/server.rs | MCP ツール定義 |
| generated/version.txt | `photocraft-cli --version` |
| generated/commands.json | `photocraft-cli commands --json`（コマンド台帳・params 書式） |
| generated/mcp-tools.json | `photocraft-cli mcp` の tools/list 結果 |
| generated/release-assets.txt | リリースの SHA256SUMS.txt（asset 名の一覧） |
