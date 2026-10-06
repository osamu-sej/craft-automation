# 本家更新の追跡設計

PhotoCraft は early alpha。コマンド名・JSON 形式は変わりうる前提で、**検知 → 判定 → 反映 → 記録**を仕組み化する。

## 全体像
| 層 | 仕組み | 検知対象 | 通知 |
|---|---|---|---|
| 1. ピン留め | `.photocraft-version` | 検証済みバージョン | - |
| 2. リリース監視 | `upstream-watch.yml`（毎日） | 新リリース（pre-release 含む） | Issue |
| 3. 文書監視 | 同上 + `.upstream/watched-paths.txt` | control-protocol / parity / roadmap / AGENTS / README の更新 | Issue |
| 4. 互換性テスト | `smoke.yml`（push・毎日） | pinned / latest 双方でレシピ実行 | latest 失敗時 Issue |
| 5. 記録 | `docs/upgrade-log.md`・`docs/commands.md` | 検証結果 | - |

## 判定ルール
- pinned 成功 / latest 成功 → 互換。ピンを更新してよい
- pinned 成功 / latest 失敗 → **破壊的変更**。Issue で対応
- 文書のみ変更 → コマンド追加・変更の可能性。`docs/commands.md` を見直す

## 更新時の手順
1. Issue の Diff / リリースを確認
2. smoke (latest) の失敗箇所を特定 → `actions/` と `docs/commands.md` を修正
3. 監視対象ファイルの Issue は `.upstream/<key>.sha` に最新 SHA を記録
4. `.photocraft-version` を更新、`scripts/snapshot-upstream.sh <新タグ>` でスナップショットを作り直し、`docs/upgrade-log.md` に追記、Issue を閉じる

## アプリでの手順
アプリの「ピン更新」ページは、上の 4 手順を飛ばせない形で進める（docs/app.md）。手作業でも、同じ内容を `.photocraft-version`・`docs/upgrade-log.md`・`.upstream/`・`scripts/snapshot-upstream.sh` で行える。

## 設計上の注意
- レシピを直書きせず `scripts/` のラッパー層を介すと、名前変更の影響を局所化できる
- Issue は件名で重複排除（同じ版・同じコミットで再起票しない）
- 本家はリリースノートが薄いため、**Diff（commits）と文書変更**を一次情報とする

## 検証結果（2026-10-05。旧「要検証」）
- リリース asset: `photocraft-<version>-linux-<arch>.tar.gz`、展開後は `photocraft-<version>-linux-<arch>/bin/photocraft-cli`。`SHA256SUMS.txt` で検証する（`scripts/fetch-photocraft.sh`）
- `photocraft-cli --version` あり（版・コミット・ビルド日）
- batch のアクションリスト形式: `[{"command", "params"}]` または `{"actions": [...]}`（`actions/grade.json`）
- 詳細と根拠は `docs/requirements.md` §9、資料は `docs/upstream-snapshot/<tag>/`

## 検知の限界
- CLI は params を検証しないため、params のキー名が変わってもスモークは成功する。ピン更新時は `scripts/snapshot-upstream.sh <新タグ>` を実行し、`generated/commands.json` の差分でレシピの使用コマンドを確認する
- 監視対象には CLI 定義（`apps/photocraft-cli/src/lib.rs`）と MCP ツール定義（`crates/automation/src/server.rs`）も含める。batch の形式（`parse_actions`）と MCP ツールの正本は文書ではなく実装にある
