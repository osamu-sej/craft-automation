#!/usr/bin/env bash
# 使い方: scripts/fetch-photocraft.sh <tag> <outdir>
# 本家リリースの Linux 版 tarball を取得し、SHA256SUMS.txt で検証して展開する。
# 標準出力には photocraft-cli のパスだけを出す（ログ・エラーは標準エラー）。
# asset 名は本家 packaging/linux/package.sh の photocraft-<version>-linux-<arch>.tar.gz
# （展開後 photocraft-<version>-linux-<arch>/bin/photocraft-cli。v0.1.1 / v0.2.0 で確認）
set -euo pipefail
TAG="${1:?tag required}"; OUT="${2:?outdir required}"
ARCH="$(uname -m)"
case "$ARCH" in x86_64|aarch64) ;; *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; esac
NAME="photocraft-${TAG#v}-linux-$ARCH"
BASE="https://github.com/storytold/photocraft/releases/download/$TAG"
mkdir -p "$OUT"
curl -fsSL -o "$OUT/$NAME.tar.gz" "$BASE/$NAME.tar.gz"
curl -fsSL -o "$OUT/SHA256SUMS.txt" "$BASE/SHA256SUMS.txt"
grep -q " $NAME.tar.gz\$" "$OUT/SHA256SUMS.txt" || { echo "$NAME.tar.gz not listed in SHA256SUMS.txt" >&2; exit 1; }
(cd "$OUT" && grep " $NAME.tar.gz\$" SHA256SUMS.txt | sha256sum -c --quiet -) >&2
tar -xzf "$OUT/$NAME.tar.gz" -C "$OUT"
CLI="$OUT/$NAME/bin/photocraft-cli"
[ -x "$CLI" ] || { echo "photocraft-cli not found in $NAME.tar.gz" >&2; exit 1; }
echo "$CLI"
