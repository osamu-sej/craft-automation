"""アプリの起動: 仮想環境の作成 → 依存の導入（requirements.txt が変わったときだけ）→ streamlit run。

run-app.command（macOS）/ run-app.bat（Windows）から呼ぶ。直接 `python3 app/launch.py` でもよい。
"""

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    if sys.version_info < (3, 10):
        print(f"Python 3.10 以上が必要です（この Python は {sys.version.split()[0]}）。https://www.python.org/downloads/ からインストールしてください。")
        return 1
    if not PY.exists():
        print("初回セットアップ: 仮想環境を作成しています…")
        venv.create(VENV, with_pip=True)
    req = ROOT / "requirements.txt"
    stamp = VENV / ".requirements.sha256"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != digest:
        print("依存パッケージを導入しています（数分かかることがあります）…")
        subprocess.run([str(PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)], check=True)
        stamp.write_text(digest, encoding="utf-8")
    print("アプリを起動します。ブラウザが開きます。終了するときはこのウィンドウを閉じてください。")
    os.chdir(ROOT)  # .streamlit/config.toml を読ませる
    return subprocess.call([str(PY), "-m", "streamlit", "run", str(ROOT / "app" / "streamlit_app.py")])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"セットアップに失敗しました（{e}）。上のメッセージを確認してください。")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)
