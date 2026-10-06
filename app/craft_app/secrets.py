"""GitHub トークンの保管（requirements.md §4: OS キーチェーン）。

トークンはファイル・ログ・履歴に書かない。環境変数 GITHUB_TOKEN があればそれを優先し、
なければ OS のキーチェーン（macOS キーチェーン / Windows 資格情報マネージャー / Linux の Secret Service）を使う。
keyring が使えない環境（Linux のコンテナなど）では環境変数だけになる。
"""

from __future__ import annotations

import os

SERVICE = "craft-automation"
ACCOUNT = "github-token"

try:  # keyring は任意。無くてもアプリは動く
    import keyring
    from keyring.errors import KeyringError
except Exception:  # noqa: BLE001 - import 時の失敗は理由を問わず「使えない」
    keyring = None  # type: ignore[assignment]

    class KeyringError(Exception):  # type: ignore[no-redef]
        pass


def keychain_available() -> bool:
    """キーチェーンに保存できる見込みがあるか（実際に使えるバックエンドがあるか）。"""
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001
        return False
    return getattr(backend, "priority", 0) > 0


def get_token() -> tuple[str | None, str]:
    """(トークン, 取得元の説明)。トークンの値そのものは画面に出さない。"""
    env = os.environ.get("GITHUB_TOKEN", "").strip()
    if env:
        return env, "環境変数 GITHUB_TOKEN"
    if keychain_available():
        try:
            value = keyring.get_password(SERVICE, ACCOUNT)
        except (KeyringError, OSError):
            value = None
        if value:
            return value, "OS のキーチェーン"
    return None, "未設定"


def save_token(token: str) -> None:
    token = token.strip()
    if not token:
        raise ValueError("トークンが空です")
    if not keychain_available():
        raise RuntimeError("この環境ではキーチェーンを使えません。環境変数 GITHUB_TOKEN で渡してください")
    try:
        keyring.set_password(SERVICE, ACCOUNT, token)
    except (KeyringError, OSError) as e:
        raise RuntimeError(f"キーチェーンに保存できませんでした: {e}") from e


def delete_token() -> None:
    if not keychain_available():
        return
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except (KeyringError, OSError):
        pass  # 無ければ何もしない
