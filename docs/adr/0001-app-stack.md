# ADR 0001: アプリの技術選定（Streamlit）

- 状態: 採用（2026-10-05）
- 関連: requirements.md §4・§5

## 背景
requirements.md §5 は Tauri 2（Rust）+ TypeScript を推奨とし、Python + Streamlit を代替案として「要ADR」としていた。利用者は macOS と Windows の両方で使う。

## 決定
**Python + Streamlit** で作る。ローカルで動くブラウザ UI とし、起動は `run-app.command`（macOS）/ `run-app.bat`（Windows）から行う。

## 理由
- 最短で使い始められる。利用者が普段使う技術で、自分で直せる
- PhotoCraft 依存部（アダプタ層）は CLI のサブプロセス呼び出しと HTTP だけなので、Rust である必要がない
- 1つのコードで macOS / Windows / Linux に対応でき、3 OS の CI でそのまま検証できる（`.github/workflows/app.yml`）

## 影響（要件からの差分）
| 要件 | Tauri 案 | 本決定 |
|---|---|---|
| §4 配布「単一バイナリ」 | .app / .exe | **Python 3.10+ が必要**。依存は初回起動時にリポジトリの `.venv/` へ自動導入 |
| §1 主環境 macOS | macOS 必須 | **macOS・Windows 両方**を対象（CI で両 OS を検証） |
| §4 性能「起動 3 秒以内」 | 可 | 2回目以降は数秒。初回は依存の導入で数分 |
| フォルダ選択 | OS のダイアログ | パスの入力（Streamlit にフォルダ選択がない） |
| §4 セキュリティ | アプリ内に閉じる | ローカル HTTP サーバー。`server.address = localhost` で外から開けないようにし、利用統計送信を切る（`.streamlit/config.toml`） |
| §4 GitHub トークンを OS キーチェーンへ | 可 | P1 では未使用（未認証 API と git で足りる）。Issue 起票（P3）で必要になったら keyring で対応する |

## 見直す条件
- Python を入れられない利用者が出た、または単一バイナリでの配布が必要になったとき
- フォルダ選択や OS 通知（FR-05）など、ブラウザ UI では不便な機能が中心になったとき

アダプタ層（`app/craft_app/`）は Streamlit に依存しないので、UI だけを差し替えられる。
