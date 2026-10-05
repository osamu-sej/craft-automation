#!/usr/bin/env bash
# 使い方: scripts/fetch-photocraft.sh <tag> <outdir>
# 本家リリースの linux-x86_64 tarball を取得して展開する（要 gh CLI）
set -euo pipefail
TAG="${1:?tag required}"; OUT="${2:?outdir required}"
mkdir -p "$OUT"
gh release download "$TAG" -R storytold/photocraft \
  --pattern '*linux-x86_64.tar.gz' --dir "$OUT" --clobber
tar -xzf "$OUT"/*linux-x86_64.tar.gz -C "$OUT"
CLI="$(find "$OUT" -type f -name photocraft-cli | head -n1)"
[ -n "$CLI" ] || { echo "photocraft-cli not found in $TAG"; exit 1; }
chmod +x "$CLI"
echo "$CLI"
