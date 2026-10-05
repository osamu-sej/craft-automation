# craft-automation アプリ化 要件定義書 (v0.2)

> v0.2（2026-10-05）: §9 の未確定事項を本家 v0.1.1 / v0.2.0 の資料と実機で確定し、FR-01〜05・07 に反映。

> 前提: 「このレポジトリ」= `craft-automation`。リポジトリが持つ**運用設計そのもの**（レシピ管理・一括実行・MCP検証・本家更新追跡）を、忠実にGUIアプリへ移植する。PhotoCraft本体の再実装は対象外。

## 1. 目的・スコープ
- **目的**: PhotoCraft（early alpha）のCLI/MCPを使った画像処理自動化を、CLI・YAML・Issue運用なしで回せるようにする。
- **In**: レシピ管理 / batch実行 / スモークテスト(pinned vs latest) / 本家更新監視 / MCP接続支援 / コマンド台帳 / アップグレード履歴。
- **Out**: 画像編集UI本体、PhotoCraft の再実装・同梱改変、クラウド同期、複数ユーザー運用。
- **ユーザー**: 単一ユーザー（ローカル利用）。macOS と Windows の両方（ADR 0001）。Linux は Should。

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
| `docs/upstream-snapshot/<tag>/` / `scripts/snapshot-upstream.sh` | 版ごとの本家資料・コマンド台帳・MCPツール定義（照合と差分の元データ） | FR-01, FR-05, FR-08 |

## 3. 機能要件（MoSCoW）
**FR-01 レシピ管理 (Must)**
- `actions/` 配下のJSONの一覧/新規/複製/編集/削除。
- 編集時にJSON構文検証。コマンド名は台帳(FR-08)と照合し、未知コマンドは警告。
- レシピごとに `tested_with`（検証済み版）と最終実行結果を保持。
- 形式（§9 Q1 で確定）: `[{"command": id, "params": {…}}, …]` または `{"actions": [...]}`。`"id"` は `"command"` の別名、`params` 省略時は `{}`。
- `tested_with` はオブジェクト形式の追加キーとしてレシピ内に保持する（CLI は `actions` 以外を無視するため互換。例: `actions/grade.json`）。
- コマンド名の照合元は、使用版の `commands --json`（スナップショットの `generated/commands.json`）。台帳(FR-08)は補助。
- CLI は params を検証しない（未知キー・範囲外・型違いでも成功）。アプリ側で params のキー名を `commands.json` の書式文字列と照合し、未知キーは警告する。範囲チェックは Could。
- 形式の解釈はアダプタ層に置き、本家の変更時に差し替え可能にする。

**FR-02 PhotoCraft バージョン管理 (Must)**
- 本家リリース一覧の取得（pre-release含む）、指定タグのバイナリ取得・展開（linux/macOS/Windows各asset）。
- ピン版と latest の併存。実行時にどちらを使うか選択。
- asset 名と展開後のパス（§9 Q2 で確定）:

  | OS | asset | 展開後の CLI |
  |---|---|---|
  | Linux（x86_64 / aarch64） | `photocraft-<ver>-linux-<arch>.tar.gz` | `photocraft-<ver>-linux-<arch>/bin/photocraft-cli` |
  | macOS（universal） | `photocraft-cli-<ver>-macos-universal.zip` | `photocraft-cli-<ver>-macos-universal/photocraft-cli` |
  | Windows（x64 / x86） | `photocraft-<ver>-windows-<arch>-portable.zip` | `photocraft-<ver>-windows-<arch>-portable/photocraft-cli.exe` |

  `<ver>` はタグから先頭の `v` を除いたもの。
- 取得物は同じリリースの `SHA256SUMS.txt` で検証し、不一致なら使わない。
- 取得失敗・asset 名変更時は、試した URL と HTTP ステータスを表示する。

**FR-03 一括実行 (Must)**
- 入力フォルダ / 出力フォルダ / レシピ / 使用バージョンを選び `photocraft-cli batch` を実行。
- 進捗・標準出力/エラーのライブ表示、キャンセル、終了コード判定。
- CLI の挙動（v0.2.0 で確認）: 入力フォルダ直下のみ対象（再帰なし）、ファイル名順。出力は `<stem>.<ext>`（`ext` は `--format`、なければ入力の拡張子）。
  - 進捗は1ファイルごとの stdout `ok    <in> -> <out>` と stderr `FAIL  <in>: <理由>` / `warning: …` を解析し、最後の `N succeeded, M failed` で集計する。
  - 終了コードは 0（全件成功）、1（1件以上失敗、必須フラグ欠落、入力フォルダ・レシピのエラー）、2（サブコマンド不明・フラグの値欠落）。入力0件は exit 0 になるため、アプリ側で事前に件数を確認する。
  - `--format` 指定で同じ stem の入力（`a.png` と `a.jpg` など）が同じ出力名になり上書きされる。実行前に警告する。
- 出力のサムネイル一覧と入出力比較（Should）。実行履歴をローカルDBに保存。

**FR-04 スモークテスト (Must)**
- `samples/smoke/in` に全レシピを適用し、出力生成を検証。pinned / latest を並列実行して結果を並べて表示。
- 判定: pinned成功・latest失敗 = 破壊的変更。結果は履歴に保存。
- 限界: CLI は params を検証しないため、スモーク成功は「params が効いている」ことを保証しない。params のキー名変更は FR-05 のコマンド台帳差分で検知する。

**FR-05 本家更新ダッシュボード (Must)**
- 新リリース検知（ピンとの差、Diffリンク、commit数）。
- 監視対象ファイル（`.upstream/watched-paths.txt`）の最新コミットSHAと記録SHAを比較し変更を表示。確認済みにすると記録SHAを更新。
- pinned と latest の `commands --json` を比較し、コマンドの追加・削除と params 書式の変更を表示する。レシピで使用中のコマンドが影響を受ける場合は強調する（Should）。
- 定期チェック（既定: 起動時＋24h毎）。変更時はOS通知。
- GitHub Issue 自動起票は Should（トークン必須。件名で重複排除：リリース/コミットSHA単位）。

**FR-06 アップグレード手順ウィザード (Should)**
- `upstream-tracking.md` の4手順を画面化: Diff確認 → smoke(latest)結果確認 → レシピ/台帳修正 → ピン更新＋`upgrade-log` 追記。
- 全工程の完了でのみピンを更新できる（スキップ不可）。

**FR-07 MCP接続支援 (Should)**
- `photocraft-cli mcp` の起動/停止、ヘッドレス/起動中アプリブリッジの切替。
- Claude 等のMCPクライアント設定スニペットを生成・コピー。公開ツール一覧の取得と保存。
- v0.2.0 以降はファイルアクセスにルート指定が必須（`--automation-read-root` / `--automation-write-root`。パスはルートからの相対のみ）。スニペットにはルートを必ず含め、既定はリポジトリの `samples/` 配下にする。
- ブリッジ接続はトークン必須（v0.2.0 以降）。スニペットには `--control-token-file <path>` を使い、トークン値は埋め込まない。
- 版によって挙動が変わる（v0.1.1 はルート指定を無視し、制御ポートは無認証）。使用版に応じてスニペットを切り替える。詳細は `mcp/README.md`。

**FR-08 コマンド台帳 (Should)**
- 使用したコマンド・params・用途・検証日の台帳。レシピから自動収集、手動編集可。

**FR-09 リポジトリ互換入出力 (Must)**
- 作業ディレクトリは `craft-automation` リポジトリ構造をそのまま使用（`actions/` `docs/` `.photocraft-version` `.upstream/`）。**アプリ独自形式にロックインしない**。アプリを使わずCLI/GitHub Actionsでも同じ資産が動くこと。

## 4. 非機能要件
| 区分 | 要件 |
|---|---|
| 配布 | ~~単一バイナリ配布~~ → ローカルのブラウザ UI。Python 3.10+ が必要で、依存は初回起動時に自動導入（ADR 0001） |
| オフライン | GitHub API以外は完全ローカル。画像・レシピを外部送信しない |
| セキュリティ | GitHubトークンはOSキーチェーン保存。ログ・レシピに秘匿情報を書かない。PhotoCraft の制御トークンはファイル（0600）で渡し、コマンドラインに直接書かない。取得バイナリは SHA256 検証 |
| 耐変更性 | PhotoCraft依存部は**アダプタ層1か所**に隔離（コマンド名・JSON形式・asset名・CLI引数） |
| 再現性 | 全実行に「使用版・レシピ内容ハッシュ・入出力パス・ログ」を記録 |
| 性能 | 起動3秒以内、UIはバッチ実行中もブロックしない |
| 可観測性 | 外部コマンド失敗時は実行コマンド全文・終了コード・stderrを表示 |
| テスト | アダプタ層はモックCLIで単体テスト。FR-04は実バイナリで結合テスト |

## 5. アーキテクチャ
- **決定（2026-10-05、[ADR 0001](adr/0001-app-stack.md)）**: Python + Streamlit。起動は `run-app.command`（macOS）/ `run-app.bat`（Windows）。実装は `app/`、使い方は [app.md](app.md)。
- 当初の推奨案: Tauri 2（Rust）+ TypeScript UI。理由: PhotoCraft自体がRust製で、同一スタックでバイナリ取得・サブプロセス制御が書きやすく、配布が軽い。
- 層: UI → アプリサービス（レシピ/実行/更新追跡）→ **PhotoCraftアダプタ** → `photocraft-cli`(subprocess) / GitHub REST。
- アダプタの実装候補: FR-03 は `photocraft-cli batch`（CLI互換を FR-09 で保証できる）。1ファイルずつの細かい制御が必要になった場合は `photocraft-cli serve`（stdio の JSON lines、1セッション維持、`batch` メソッドあり）も使える。
- 永続化: 実行履歴のみSQLite（アプリデータ領域）。それ以外の正本は**リポジトリのファイル**。
- 代替案だった Python+Streamlit を採用（最短で動き、macOS / Windows を1つのコードで扱える。配布性の差は ADR 0001 に記録）。
- 対応: アダプタ層 = `app/craft_app/photocraft.py`（本家依存の知識）と `releases.py`、レシピ = `recipes.py`、実行と履歴 = `jobs.py`、画面 = `app/views/`。

## 6. データモデル（概念）
- `Recipe`: name, path, json, tested_with, last_result
- `Run`: id, recipe_hash, photocraft_version, in_dir, out_dir, status, exit_code, log, started_at
- `UpstreamState`: pinned, latest, watched_path→recorded_sha, last_checked_at
- `CommandEntry`: command, params_example, purpose, verified_at

## 7. 受け入れ基準（主要）
1. FR-01: 不正JSONは保存前に拒否。未知コマンドは警告が出る。
2. FR-02: ピン版と latest を切り替えて `--version` で確認できる。SHA256 不一致の取得物は使われない。
3. FR-03: 10枚のPNGに対しbatchが完走し、出力一覧が表示され、履歴に残る。
4. FR-04: pinned成功/latest失敗の状況を再現し「破壊的変更」と判定表示される（モックで検証可）。
5. FR-05: 本家に新タグがある状態で、ピンとの差とDiffリンクが表示される。確認済み操作で記録SHAがファイルに反映される。
6. FR-09: アプリで編集したレシピを、アプリなしで `photocraft-cli batch` に渡して同じ結果になる。

## 8. 実装フェーズ
- **P0（1〜2日）**: 本家 `docs/control-protocol.md` 等の読解、batch JSON形式の確定、アダプタ層のI/F定義。
  - 2026-10-05: 読解と §9 の確定は完了（スナップショット `docs/upstream-snapshot/v0.2.0/`）。残りはアダプタ層の I/F 定義。
- **P1 MVP**: FR-01, 02, 03, 09
  - 2026-10-05: 実装済み（Streamlit。テストは `tests/`、macOS / Windows / Linux の CI は `.github/workflows/app.yml`）。FR-03 の入出力比較（Should）も実装。ピンの更新は FR-06（P3）まで手作業
- **P2**: FR-04, 05（更新追跡の中核）
- **P3**: FR-06, 07, 08、Issue自動起票

## 9. 確定事項（P0 で解消。2026-10-05）
本家 v0.1.1 / v0.2.0 の資料と Linux 版バイナリの実機確認で確定した。根拠の資料は `docs/upstream-snapshot/v0.2.0/`。

| # | 問い | 回答 | 根拠 |
|---|---|---|---|
| Q1 | `batch --actions` の JSON スキーマ | `[{"command": id, "params": {…}}]` または `{"actions": [...]}`。`"id"` は `"command"` の別名、`params` は省略可。他のキーは無視。**params は検証されない**（未知キー・範囲外・型違いでも成功） | `apps/photocraft-cli/src/lib.rs` の `parse_actions`。実機で配列形式・`{"actions"}` 形式・`id` 別名・params 省略を確認 |
| Q2 | リリース asset 命名と展開後のバイナリ名 | FR-02 の表のとおり。v0.1.1 と v0.2.0 で asset 構成は同一。全 asset の `SHA256SUMS.txt` が付く | 本家 `packaging/*/package.*`。3 OS の asset を取得して確認 |
| Q3 | MCP の公開ツールと認証 | 18 ツール（両版同じ）。v0.2.0 からファイルアクセスにルート指定が必須、ブリッジにトークン認証。詳細は `mcp/README.md` | `crates/automation/src/server.rs`、`docs/control-protocol.md`、実機の tools/list |
| Q4 | バージョン取得手段 | `photocraft-cli --version` → `photocraft-cli 0.2.0 (ad8632173, 2026-10-05)`（版・コミット・ビルド日） | `lib.rs`、実機 |
| Q5 | 本家の API 安定性方針 | 明文化された方針はない（early alpha）。0.x の minor 版で破壊的変更が入る（v0.2.0 の MCP ファイルアクセス）。リリースはドラフト作成後に手動公開。`-rc.N` はプレリリース | `README.md`、`docs/releasing.md`、v0.1.1→v0.2.0 の差分 |
| Q6 | GitHub Actions ワークフローの実機検証 | `smoke.yml`: **確認済み**（pinned / latest とも取得・SHA256 検証・grade レシピ成功。latest は `gh release list` で v0.2.0 に解決）。取り込み直後は実行権限なしで失敗していた（修正済み）。`upstream-watch.yml`: **未実行**（schedule / 手動実行のみ。初回実行で監視対象ごとに Issue が起票される） | Actions run 37375408633（2026-10-05） |

### v0.1.1 → v0.2.0 の主な変化（ピン更新の判断材料）
- CLI の `run` / `batch` / `--version` は互換（スモークは両版で成功）
- MCP / `serve`: ファイルアクセスがルート指定必須に（**破壊的**）。制御ポートにトークン認証
- コマンド: 739 → 748 件。追加9件、削除なし。params 書式の変更35件（キー削除なし）

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
| 3 | `actions/grade.json` | レシピ形式の実例（`tested_with` 付きオブジェクト形式） |
| 3 | `scripts/snapshot-upstream.sh` | B 群の生成手順 |
| 3 | `.gitignore` | 管理対象外の境界 |

### B. 本家 storytold/photocraft（取得して渡す。P0で必須）
| 優先 | ファイル | 読ませる理由 |
|---|---|---|
| 1 | `README.md` | CLI/MCP/controlの概要（取得済みの内容と突合） |
| 1 | `docs/control-protocol.md` | 制御プロトコル・コマンド仕様（Q1, Q3） |
| 1 | `AGENTS.md` | エージェント向け操作指針 |
| 2 | `docs/parity.md` / `docs/roadmap.md` | 実装範囲・変更予定（Q5） |
| 2 | `apps/photocraft-cli/src/lib.rs` | CLI 定義と `parse_actions`（Q1） |
| 2 | `crates/automation/src/server.rs` | MCP ツール定義（Q3） |
| 2 | `generated/commands.json` / `generated/mcp-tools.json` | コマンド台帳と params 書式、MCP ツール一覧（実機から生成） |
| 3 | `generated/release-assets.txt` | リリース asset 一覧（Q2） |

### C. 渡し方
1. 本リポジトリ全体 + 本家B群を `docs/upstream-snapshot/<tag>/` に置く。`scripts/snapshot-upstream.sh <tag>` で生成し、手で編集しない（版の混在を防ぐ）。ピンを更新したら同じタグで作り直す。
2. エージェントへの指示: 「`docs/requirements.md` を正とし、§2の対応表にない機能は作らない。PhotoCraft依存はアダプタ層のみ。§9は推測せず本家資料で確定してから実装」。
