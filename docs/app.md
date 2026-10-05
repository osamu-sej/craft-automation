# アプリの使い方

craft-automation の運用（レシピ管理・一括実行・PhotoCraft のバージョン管理）をブラウザの画面で行うアプリ。自分の PC の中だけで動く。要件は [requirements.md](requirements.md)、技術選定は [adr/0001-app-stack.md](adr/0001-app-stack.md)。

## 準備（初回のみ）
1. **Python 3.10 以上**を入れる: https://www.python.org/downloads/
   - Windows はインストーラーの最初の画面で「Add python.exe to PATH」にチェックを入れる
   - macOS 標準の python3（3.9）では動かない
2. このリポジトリを PC に置く（`git clone https://github.com/osamu-sej/craft-automation`、または GitHub の「Code → Download ZIP」を展開）

## 起動
| OS | 操作 |
|---|---|
| macOS | Finder で `run-app.command` をダブルクリック |
| Windows | エクスプローラーで `run-app.bat` をダブルクリック |
| ターミナル | `python3 app/launch.py`（Windows は `py -3 app\launch.py`） |

- 初回は依存パッケージの導入で数分かかる（リポジトリ内の `.venv/` に入る。2回目からはすぐ起動する）
- ブラウザで http://localhost:8501 が開く。開かなければこのアドレスを手で開く
- **終了**: 起動したターミナル（黒い画面）のウィンドウを閉じる
- macOS で「開発元を確認できない」と出たら、`run-app.command` を右クリック → 「開く」。ZIP でダウンロードした場合に出る

## 最初にやること: PhotoCraft の導入
1. 左の「**バージョン**」を開く
2. 「導入する版」でピンの版（`.photocraft-version`、現在 v0.2.0）を選び、「**導入**」
3. 本家リリースから、この PC の OS 向けの CLI を取得し、SHA256 を検証してから `.bin/<版>/` に展開する（macOS 約 20MB、Windows 約 30MB）

左のサイドバーの「使用バージョン」で、実行に使う版を切り替えられる。

## 一括実行
1. 「**一括実行**」でレシピ・入力フォルダ・出力フォルダを指定する
   - パスはリポジトリ基準の相対パス（例: `samples/in`）か絶対パス
   - Windows の「パスのコピー」で付く `"` はそのまま貼ってよい
   - macOS は Finder でフォルダを選んで ⌥⌘C でパスをコピーできる
2. 処理件数や注意（出力名の重複、既存ファイルの上書き、レシピの警告）を確認して「**実行**」
3. 実行中も画面は操作できる。「キャンセル」で止められる
4. 終わると、成功・失敗の件数、実行コマンド全文、失敗理由、出力のサムネイル、入出力の比較が出る
5. 成功したら「このレシピを vX.Y.Z で検証済みにする」で `tested_with` を記録できる

処理されるのは入力フォルダ直下の画像だけ（サブフォルダは対象外）。入力と出力を同じフォルダにはできない（元画像が上書きされるため）。

## レシピ
- 「**レシピ**」で `actions/*.json` の一覧・編集・新規作成・複製・削除ができる
- 編集中に検証する。JSON の誤りは保存できない。未知のコマンドや、書式にない params のキーは警告になる
  - PhotoCraft の CLI は params の誤りを黙って無視するため、警告は必ず確認する
- 右の「コマンドを探す」で、使用バージョンのコマンド一覧（748 件）から ID・名前・メニューで探し、params の書式を見てレシピに追加できる
- 保存したファイルはアプリなしでも使える: `photocraft-cli batch --actions actions/<名前>.json --in <入力> --out <出力>`

## 履歴
「**履歴**」に全実行が残る（使用版、レシピ内容の SHA256、入出力パス、実行コマンド全文、終了コード、ログ）。保存先は次のとおり。

| OS | 場所 |
|---|---|
| macOS | `~/Library/Application Support/craft-automation/runs.sqlite` |
| Windows | `%APPDATA%\craft-automation\runs.sqlite` |

## 外部との通信
- GitHub（本家のリリース一覧と CLI の取得）だけ。画像やレシピは外に送らない
- アプリは自分の PC（localhost）からだけ開ける。Streamlit の利用統計送信は切ってある（`.streamlit/config.toml`）
- リリース一覧は GitHub API（未認証で 1 時間 60 回まで）。使えないときは git のタグで代用する。環境変数 `GITHUB_TOKEN` があれば使う

## まだできないこと（requirements.md §8 の P2 以降）
- スモークテスト（pinned / latest の比較）: `scripts/smoke.sh` と GitHub Actions の smoke で代用
- 本家更新ダッシュボード: GitHub Actions の upstream-watch（Issue）で代用
- ピンの更新: [upstream-tracking.md](upstream-tracking.md) の手順で `.photocraft-version` を書き換える
- MCP 接続支援、コマンド台帳（`docs/commands.md`）の自動更新

## 困ったとき
| 症状 | 対処 |
|---|---|
| 「Python 3.10 以上が見つかりません」 | python.org から入れ直す。Windows は PATH のチェックを忘れずに |
| 導入で「HTTP 404」 | その版に、この OS 向けの asset がない。別の版を選ぶ |
| 導入で「SHA256 が一致しません」 | 通信の途中で壊れた可能性。もう一度導入する |
| リリース一覧が出ない | 社内ネットワークで GitHub が遮断されている可能性。タグを直接入力して導入する |
| 依存の導入に失敗する | `.venv` フォルダを削除してから起動し直す |
