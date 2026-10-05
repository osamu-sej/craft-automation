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
4. `.photocraft-version` を更新、`docs/upgrade-log.md` に追記、Issue を閉じる

## 設計上の注意
- レシピを直書きせず `scripts/` のラッパー層を介すと、名前変更の影響を局所化できる
- Issue は件名で重複排除（同じ版・同じコミットで再起票しない）
- 本家はリリースノートが薄いため、**Diff（commits）と文書変更**を一次情報とする

## 要検証（実装時の仮定）
- リリース asset 名 `*linux-x86_64.tar.gz` と、展開後に `photocraft-cli` が含まれること
- `photocraft-cli --version` の有無
- batch のアクションリスト形式（`actions/` 最初のレシピ作成時に確定）
