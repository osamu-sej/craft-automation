#!/usr/bin/env bash
# 使い方: scripts/smoke.sh <path-to-photocraft-cli>
# actions/*.json を samples/smoke/in に適用し、出力が生成されることを確認する
set -euo pipefail
CLI="${1:?photocraft-cli path required}"
shopt -s nullglob
files=(actions/*.json)
if [ ${#files[@]} -eq 0 ]; then echo "::notice::actions/ にレシピなし。スキップ"; exit 0; fi
"$CLI" --version 2>/dev/null || true
fail=0
for f in "${files[@]}"; do
  name="$(basename "$f" .json)"; out="out/smoke/$name"; mkdir -p "$out"
  echo "== $name"
  if ! "$CLI" batch --actions "$f" --in samples/smoke/in --out "$out"; then
    echo "::error::batch failed: $name"; fail=1; continue
  fi
  [ -n "$(ls -A "$out")" ] || { echo "::error::no output: $name"; fail=1; }
done
exit $fail
