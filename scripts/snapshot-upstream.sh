#!/usr/bin/env bash
# 使い方: scripts/snapshot-upstream.sh <tag>
# 本家の指定タグの資料を docs/upstream-snapshot/<tag>/ に固定する（requirements.md §10-C）。
# 文書・CLI定義はタグの時点のファイルを複写し、コマンド台帳・MCPツール一覧はそのタグの
# リリースバイナリから生成する。版の混在を防ぐため、ディレクトリは毎回作り直す。
set -euo pipefail
TAG="${1:?tag required}"
UP=https://github.com/storytold/photocraft
DEST="docs/upstream-snapshot/$TAG"
FILES=(
  README.md AGENTS.md docs/control-protocol.md docs/parity.md docs/roadmap.md
  apps/photocraft-cli/src/lib.rs     # CLI定義・batch のアクションリスト形式（parse_actions）
  crates/automation/src/server.rs    # MCP ツール定義
  LICENSE-MIT LICENSE-APACHE NOTICE
)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

git clone -q --depth 1 --branch "$TAG" "$UP" "$TMP/src" 2>/dev/null
SHA="$(git -C "$TMP/src" rev-parse HEAD)"
CLI="$(scripts/fetch-photocraft.sh "$TAG" "$TMP/bin")"

rm -rf "$DEST"; mkdir -p "$DEST/generated"
for f in "${FILES[@]}"; do install -D -m 644 "$TMP/src/$f" "$DEST/$f"; done
cp "$TMP/bin/SHA256SUMS.txt" "$DEST/generated/release-assets.txt"
"$CLI" --version > "$DEST/generated/version.txt"
"$CLI" commands --json > "$DEST/generated/commands.json"

# MCP: initialize → tools/list を stdio で1往復し、ツール定義を保存する
coproc MCP { "$CLI" mcp 2>/dev/null; }
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"craft-automation","version":"0"}}}' >&"${MCP[1]}"
IFS= read -r -t 30 _ <&"${MCP[0]}"
printf '%s\n' '{"jsonrpc":"2.0","method":"notifications/initialized"}' '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' >&"${MCP[1]}"
IFS= read -r -t 30 LIST <&"${MCP[0]}"
kill "$MCP_PID" 2>/dev/null || true
jq '.result.tools | sort_by(.name)' <<<"$LIST" > "$DEST/generated/mcp-tools.json"

cat > "$DEST/SOURCE.md" <<EOF
# 本家スナップショット $TAG

- 取得元: $UP/tree/$TAG （commit \`$SHA\`）
- 生成: \`scripts/snapshot-upstream.sh $TAG\` またはアプリの「ピン更新」（手で編集しない）
- ライセンス: 本家は MIT OR Apache-2.0。同梱の LICENSE-MIT / LICENSE-APACHE / NOTICE を参照

| ファイル | 内容 |
|---|---|
| README.md, AGENTS.md, docs/*.md | 本家文書（$TAG 時点） |
| apps/photocraft-cli/src/lib.rs | CLI 定義。\`parse_actions\` が batch のアクションリスト形式の正本 |
| crates/automation/src/server.rs | MCP ツール定義 |
| generated/version.txt | \`photocraft-cli --version\` |
| generated/commands.json | \`photocraft-cli commands --json\`（コマンド台帳・params 書式） |
| generated/mcp-tools.json | \`photocraft-cli mcp\` の tools/list 結果 |
| generated/release-assets.txt | リリースの SHA256SUMS.txt（asset 名の一覧） |
EOF
echo "$DEST"
