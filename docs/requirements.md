# craft-automation アプリ化 要件定義書 (v0.1)

> 前提: 「このレポジトリ」= `craft-automation`。リポジトリが持つ**運用設計そのもの**（レシピ管理・一括実行・MCP検証・本家更新追跡）を、忠実にGUIアプリへ移植する。PhotoCraft本体の再実装は対象外。

## 1. 目的・スコープ
- **目的**: PhotoCraft（early alpha）のCLI/MCPを使った画像処理自動化を、CLI・YAML・Issue運用なしで回せるようにする。
- **In**: レシピ管理 / batch実行 / スモークテスト(pinned vs latest) / 本家更新監視 / MCP接続支援 / コマンド台帳 / アップグレード履歴。
- **Out**: 画像編集UI本体、PhotoCraft の再実装・同梱改変、クラウド同期、複数ユーザー運用。
- **ユーザー**: 単一ユーザー（ローカル利用）。主環境は macOS、Windows/Linux は Should。

## 2. 忠実性の定義（トレーサビリティ）
リポジトリの各要素を、アプリの機能に1対1で対応させる。**対応が取れない機能は追加しない。**

| リポジトリ資産 | アプリでの対応 | 要件ID |
|---|---|---|
| `actions/*.json` | レシピ一覧・編集・検証 | FR-01 |
| `scripts/fetch-photocraft.sh` | バージョン管理（取得・切替） | FR-02 |
| `.photocraft-version` | ピン（検証済み版）の保持・更新 | FR-02, FR-06 |
| `batch` 実行 / `samples/` | 一括実行・出力確認 | FR-03 |
| `scripts/smoke.sh` / `smoke.yml` | スモークテスト（pinned/latest） | FR-04 |
| `upstream-watch.yml` / `.upstream/` | 本家更新ダッシュボード | FR-05 |
| `docs/upstream-tracking.md` の判定ルール | 判定ロジックと更新手順ウィザード | FR-05, FR-06 |
| `mcp/README.md` | MCP起動・接続設定の生成 | FR-07 |
| `docs/commands.md` | コマンド台帳 | FR-08 |
| `docs/upgrade-log.md` | 履歴の自動記録 | FR-06 |

## 3. 機能要件（MoSCoW）
**FR-01 レシピ管理 (Must)**
- `actions/` 配下のJSONの一覧/新規/複製/編集/削除。
- 編集時にJSON構文検証。コマンド名は台帳(FR-08)と照合し、未知コマンドは警告。
- レシピごとに `tested_with`（検証済み版）と最終実行結果を保持。
- ※ アクションリストの正式スキーマは未確定（§9 Q1）。スキーマはアダプタ層で差し替え可能にする。

**FR-02 PhotoCraft バージョン管理 (Must)**
- 本家リリース一覧の取得（pre-release含む）、指定タグのバイナリ取得・展開（linux/macOS/Windows各asset）。
- ピン版と latest の併存。実行時にどちらを使うか選択。
- 取得失敗・asset名変更時は原因を表示（asset名は仮定、§9 Q2）。

**FR-03 一括実行 (Must)**
- 入力フォルダ / 出力フォルダ / レシピ / 使用バージョンを選び `photocraft-cli batch` を実行。
- 進捗・標準出力/エラーのライブ表示、キャンセル、終了コード判定。
- 出力のサムネイル一覧と入出力比較（Should）。実行履歴をローカルDBに保存。

**FR-04 スモークテスト (Must)**
- `samples/smoke/in` に全レシピを適用し、出力生成を検証。pinned / latest を並列実行して結果を並べて表示。
- 判定: pinned成功・latest失敗 = 破壊的変更。結果は履歴に保存。

**FR-05 本家更新ダッシュボード (Must)**
- 新リリース検知（ピンとの差、Diffリンク、commit数）。
- 監視対象ファイル（`.upstream/watched-paths.txt`）の最新コミットSHAと記録SHAを比較し変更を表示。確認済みにすると記録SHAを更新。
- 定期チェック（既定: 起動時＋24h毎）。変更時はOS通知。
- GitHub Issue 自動起票は Should（トークン必須。件名で重複排除：リリース/コミットSHA単位）。

**FR-06 アップグレード手順ウィザード (Should)**
- `upstream-tracking.md` の4手順を画面化: Diff確認 → smoke(latest)結果確認 → レシピ/台帳修正 → ピン更新＋`upgrade-log` 追記。
- 全工程の完了でのみピンを更新できる（スキップ不可）。

**FR-07 MCP接続支援 (Should)**
- `photocraft-cli mcp` の起動/停止、ヘッドレス/起動中アプリブリッジの切替。
- Claude 等のMCPクライアント設定スニペットを生成・コピー。公開ツール一覧の取得と保存。

**FR-08 コマンド台帳 (Should)**
- 使用したコマンド・params・用途・検証日の台帳。レシピから自動収集、手動編集可。

**FR-09 リポジトリ互換入出力 (Must)**
- 作業ディレクトリは `craft-automation` リポジトリ構造をそのまま使用（`actions/` `docs/` `.photocraft-version` `.upstream/`）。**アプリ独自形式にロックインしない**。アプリを使わずCLI/GitHub Actionsでも同じ資産が動くこと。

## 4. 非機能要件
| 区分 | 要件 |
|---|---|
| 配布 | デスクトップアプリ（macOS必須）。単一バイナリ配布 |
| オフライン | GitHub API以外は完全ローカル。画像・レシピを外部送信しない |
| セキュリティ | GitHubトークンはOSキーチェーン保存。ログ・レシピに秘匿情報を書かない |
| 耐変更性 | PhotoCraft依存部は**アダプタ層1か所**に隔離（コマンド名・JSON形式・asset名・CLI引数） |
| 再現性 | 全実行に「使用版・レシピ内容ハッシュ・入出力パス・ログ」を記録 |
| 性能 | 起動3秒以内、UIはバッチ実行中もブロックしない |
| 可観測性 | 外部コマンド失敗時は実行コマンド全文・終了コード・stderrを表示 |
| テスト | アダプタ層はモックCLIで単体テスト。FR-04は実バイナリで結合テスト |

## 5. 推奨アーキテクチャ（要ADR）
- **推奨**: Tauri 2（Rust）+ TypeScript UI。理由: PhotoCraft自体がRust製で、同一スタックでバイナリ取得・サブプロセス制御が書きやすく、配布が軽い。
- 層: UI → アプリサービス（レシピ/実行/更新追跡）→ **PhotoCraftアダプタ** → `photocraft-cli`(subprocess) / GitHub REST。
- 永続化: 実行履歴のみSQLite（アプリデータ領域）。それ以外の正本は**リポジトリのファイル**。
- 代替案（要比較）: Python+Streamlit（最短で動く試作向き。配布性は劣る）。

## 6. データモデル（概念）
- `Recipe`: name, path, json, tested_with, last_result
- `Run`: id, recipe_hash, photocraft_version, in_dir, out_dir, status, exit_code, log, started_at
- `UpstreamState`: pinned, latest, watched_path→recorded_sha, last_checked_at
- `CommandEntry`: command, params_example, purpose, verified_at

## 7. 受け入れ基準（主要）
1. FR-01: 不正JSONは保存前に拒否。未知コマンドは警告が出る。
2. FR-02: ピン版と latest を切り替えて `--version` 相当（または実行成功）で確認できる。
3. FR-03: 10枚のPNGに対しbatchが完走し、出力一覧が表示され、履歴に残る。
4. FR-04: pinned成功/latest失敗の状況を再現し「破壊的変更」と判定表示される（モックで検証可）。
5. FR-05: 本家に新タグがある状態で、ピンとの差とDiffリンクが表示される。確認済み操作で記録SHAがファイルに反映される。
6. FR-09: アプリで編集したレシピを、アプリなしで `photocraft-cli batch` に渡して同じ結果になる。

## 8. 実装フェーズ
- **P0（1〜2日）**: 本家 `docs/control-protocol.md` 等の読解、batch JSON形式の確定、アダプタ層のI/F定義。
- **P1 MVP**: FR-01, 02, 03, 09
- **P2**: FR-04, 05（更新追跡の中核）
- **P3**: FR-06, 07, 08、Issue自動起票

## 9. 未確定事項（P0で解消）
- Q1: `batch --actions` のJSONスキーマ（本家CLI実装/ドキュメントで確認）
- Q2: リリースasset命名（`*linux-x86_64.tar.gz` は仮定）、macOS/Windows の展開後バイナリ名
- Q3: `photocraft-cli mcp` が公開するツール一覧と認証方式
- Q4: `--version` 等のバージョン取得手段
- Q5: 本家のAPI安定性方針（roadmap/parityの記載）
- Q6: GitHub Actionsワークフローは未実機検証（本アプリはActions非依存で同機能を持つ）

## 10. 読み込ませるファイル（AIコーディングエージェント向け）
一覧の機械可読版: `docs/context-files.txt`

### A. このリポジトリ（そのまま渡す）
| 優先 | ファイル | 読ませる理由 |
|---|---|---|
| 1 | `docs/requirements.md`（本書） | 要件の正本 |
| 1 | `docs/upstream-tracking.md` | 判定ルール・更新手順＝FR-04〜06の仕様 |
| 1 | `README.md` | 目的・構成・コマンド例 |
| 2 | `.github/workflows/upstream-watch.yml` | 更新検知ロジック（FR-05の参照実装） |
| 2 | `.github/workflows/smoke.yml` | pinned/latest 並列テスト（FR-04の参照実装） |
| 2 | `scripts/fetch-photocraft.sh` | バイナリ取得手順（FR-02） |
| 2 | `scripts/smoke.sh` | スモーク判定（FR-04） |
| 2 | `.photocraft-version` / `.upstream/watched-paths.txt` | ピンと監視対象の形式（FR-09） |
| 3 | `docs/commands.md` / `docs/upgrade-log.md` / `mcp/README.md` | 台帳・履歴・MCP（FR-06〜08） |
| 3 | `.gitignore` | 管理対象外の境界 |

### B. 本家 storytold/photocraft（取得して渡す。P0で必須）
| 優先 | ファイル | 読ませる理由 |
|---|---|---|
| 1 | `README.md` | CLI/MCP/controlの概要（取得済みの内容と突合） |
| 1 | `docs/control-protocol.md` | 制御プロトコル・コマンド仕様（Q1, Q3） |
| 1 | `AGENTS.md` | エージェント向け操作指針 |
| 2 | `docs/parity.md` / `docs/roadmap.md` | 実装範囲・変更予定（Q5） |
| 2 | `photocraft-cli` のcrate内、batch/mcp/run のCLI定義とアクションリストの型定義 | JSONスキーマ確定（Q1）。パスは本家リポジトリで確認 |
| 3 | 最新リリースのasset一覧（各OS） | asset命名確定（Q2） |

### C. 渡し方
1. 本リポジトリ全体 + 本家B群を `docs/upstream-snapshot/` にコピー（検証版タグ付き。バージョン混在を防ぐ）。
2. エージェントへの指示: 「`docs/requirements.md` を正とし、§2の対応表にない機能は作らない。PhotoCraft依存はアダプタ層のみ。§9は推測せず本家資料で確定してから実装」。
