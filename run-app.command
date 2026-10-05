#!/bin/bash
# craft-automation アプリを起動する（macOS: Finder でダブルクリック。Linux でも ./run-app.command で動く）
cd "$(dirname "$0")" || exit 1
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    "$c" app/launch.py
    status=$?
    [ $status -ne 0 ] && read -r -p "Enter で閉じます" _
    exit $status
  fi
done
echo "Python 3.10 以上が見つかりません。https://www.python.org/downloads/ からインストールしてください。"
read -r -p "Enter で閉じます" _
exit 1
