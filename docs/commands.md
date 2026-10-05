# コマンド一覧メモ

PhotoCraft のコマンドレジストリ（v0.2.0 で 748 件）のうち、使ったものを記録する。
全件と params 書式の正本は `photocraft-cli commands --json`（スナップショット: `docs/upstream-snapshot/<tag>/generated/commands.json`）。

**注意**: CLI は params を検証しない。未知のキー・範囲外の値・型違いでもエラーにならず成功する（v0.2.0 で確認）。レシピ作成時は下表と `commands.json` の書式でキー名を確認すること。

| コマンド | params（例） | 用途 | 使用レシピ | 検証日 |
|---|---|---|---|---|
| filter.sharpen.smartSharpen | {"amount":80} | シャープ。書式 `{"amount":1..500=100,"radius":0.1..64=1,"reduceNoise":0..100=10}` | grade | 2026-10-05 (v0.1.1, v0.2.0) |
| layer.newAdjustmentLayer.curves | {"points":[[0,0],[64,56],[192,204],[255,255]]} | トーンカーブ（調整レイヤー）。`[[in,out],…]` 0..255、2..19点。`red`/`green`/`blue` でチャンネル別 | grade | 2026-10-05 (v0.1.1, v0.2.0) |
| file.new | {"width":64,"height":64,"background":"#808080"} | 新規ドキュメント（`run --new` に渡す） | smoke 入力生成 | 2026-10-05 (v0.1.1) |
| paint.stroke | {"points":[[8,8,1],[56,56,1]],"size":8,"color":"#d03030"} | ブラシストローク | smoke 入力生成 | 2026-10-05 (v0.1.1) |

## 版間の変化（v0.1.1 → v0.2.0）
- 追加: `brush.presets.importAbr`, `gradient.presets.importGrd`, `paint.backgroundEraser`, `paint.magicEraser`, `plugin.install/list/reload/remove/run`（739 → 748 件）
- params 書式の変更: 35 件（`image.adjustments.*` 13、`layer.newAdjustmentLayer.*` 13 ほか）。キーの削除はなし。27 件はキー追加、残りは既定値の明記など（例: hueSaturation に `reds`〜`magentas`、`filter.other.maximum` に `preserve`）
- 削除: なし
