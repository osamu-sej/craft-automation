"""レシピ（actions/*.json）の一覧・検証・保存（requirements.md FR-01）。

ファイルがそのまま `photocraft-cli batch --actions` に渡せる形を保つ（FR-09）。
`tested_with` はオブジェクト形式の追加キーとして持つ（CLI は無視する）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import photocraft

TEMPLATE = '{\n  "actions": [\n    {"command": "filter.sharpen.smartSharpen", "params": {"amount": 80}}\n  ]\n}\n'

# Windows でも使えるファイル名（拡張子 .json は自動で付ける）
_NAME = re.compile(r'^[^\\/:*?"<>|\x00-\x1f.][^\\/:*?"<>|\x00-\x1f]*$')


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    steps: list[photocraft.Step] = field(default_factory=list)
    form: str = ""  # "array" / "object"
    tested_with: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(text: str, registry: dict[str, photocraft.Command] | None = None) -> Validation:
    """JSON 構文とアクションリスト形式を検証する。registry があればコマンド名と params キーも照合する。

    エラーは保存を止める。警告（未知コマンド・未知キー）は保存できる。
    CLI は params を検証しないため、未知キーは実行しても黙って無視される。
    """
    v = Validation()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        v.errors.append(f"JSON の構文エラー（{e.lineno} 行 {e.colno} 列）: {e.msg}")
        return v
    v.form = "array" if isinstance(data, list) else "object" if isinstance(data, dict) else ""
    if isinstance(data, dict) and "tested_with" in data:
        if isinstance(data["tested_with"], str):
            v.tested_with = data["tested_with"]
        else:
            v.errors.append('"tested_with" は文字列にしてください（例: "v0.2.0"）')
    v.steps, errs = photocraft.parse_actions(data)
    v.errors += errs
    if registry is not None:
        for s in v.steps:
            cmd = registry.get(s.command)
            if cmd is None:
                v.warnings.append(f"ステップ {s.index + 1}: 未知のコマンド `{s.command}`")
                continue
            known = photocraft.param_keys(cmd.params_doc)
            if known is None:
                continue
            unknown = sorted(set(s.params) - known)
            if unknown:
                v.warnings.append(f"ステップ {s.index + 1}（{s.command}）: 書式にないキー {', '.join(unknown)}（CLI は無視します）")
    return v


@dataclass(frozen=True)
class Recipe:
    name: str
    path: Path
    text: str

    @property
    def hash(self) -> str:
        return content_hash(self.text)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collection_hash(recs: list[Recipe]) -> str:
    """全レシピをまとめた内容ハッシュ。レシピが 1 つでも変わる・増減すると変わる。"""
    return hashlib.sha256("\n".join(f"{r.name}\t{r.hash}" for r in sorted(recs, key=lambda r: r.name)).encode("utf-8")).hexdigest()


def list_recipes(actions_dir: Path) -> list[Recipe]:
    if not actions_dir.is_dir():
        return []
    return [Recipe(p.stem, p, p.read_text(encoding="utf-8")) for p in sorted(actions_dir.glob("*.json"))]


def check_name(name: str) -> str | None:
    """ファイル名として使えなければ理由を返す。"""
    if not name:
        return "名前を入力してください"
    if not _NAME.match(name):
        return '名前に \\ / : * ? " < > | は使えません。先頭を . にもできません'
    return None


def path_for(actions_dir: Path, name: str) -> Path:
    return actions_dir / f"{name}.json"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(actions_dir: Path, name: str, text: str, *, overwrite: bool) -> Path:
    """検証エラーがあれば保存しない（受け入れ基準 1）。"""
    if (msg := check_name(name)) is not None:
        raise ValueError(msg)
    v = validate(text)
    if not v.ok:
        raise ValueError("; ".join(v.errors))
    path = path_for(actions_dir, name)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path.name} はすでにあります")
    _atomic_write(path, text)
    return path


def delete(path: Path) -> None:
    path.unlink()


def mark_tested(path: Path, tag: str) -> None:
    """tested_with を tag にする。配列形式はオブジェクト形式に変換する（CLI 互換のまま）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"tested_with": tag, "actions": data}
    else:
        data = {"tested_with": tag, **{k: v for k, v in data.items() if k != "tested_with"}}
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def append_step(text: str, command: str) -> str:
    """エディタの JSON 末尾にステップを追加した JSON を返す（解析できなければ ValueError）。"""
    data = json.loads(text)
    step = {"command": command, "params": {}}
    if isinstance(data, list):
        data.append(step)
    elif isinstance(data, dict) and isinstance(data.get("actions"), list):
        data["actions"].append(step)
    else:
        raise ValueError("アクションリストの形式ではありません")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
