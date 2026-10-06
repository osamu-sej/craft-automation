"""コマンド台帳（requirements.md FR-08）。正本は docs/commands.md の最初の表。

表の外（見出し・注意書き・「版間の変化」など）は一切変えず、表だけを読み書きする（FR-09）。
列は「コマンド | params（例） | 用途 | 使用レシピ | 検証日」。P1 以前の 4 列の表も読める（書くときに 5 列にする）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import photocraft, recipes

HEADER = ["コマンド", "params（例）", "用途", "使用レシピ", "検証日"]
_SEP = "|---|---|---|---|---|"
# 列名の先頭一致（"params（例）" と "params" のどちらも受ける）
_KEYS = {"command": "コマンド", "params": "params", "purpose": "用途", "recipes": "使用レシピ", "verified": "検証日"}


@dataclass(frozen=True)
class Row:
    command: str
    params: str = ""
    purpose: str = ""
    recipes: str = ""  # "grade, tone"（名前順、カンマ区切り）
    verified: str = ""  # "2026-10-06 (v0.1.1, v0.2.0)"

    def as_dict(self) -> dict[str, str]:
        return {"command": self.command, "params": self.params, "purpose": self.purpose, "recipes": self.recipes, "verified": self.verified}


@dataclass
class Ledger:
    before: list[str]  # 表より前の行
    rows: list[Row]
    after: list[str]  # 表より後の行
    separator: str = _SEP  # 元の区切り行（往復で変えないため）
    has_table: bool = True

    def render(self) -> str:
        if not self.has_table:
            table = []
        else:
            table = ["| " + " | ".join(HEADER) + " |", self.separator] + [_row_line(r) for r in self.rows]
        return "\n".join(self.before + table + self.after) + "\n"


def _cell(s: str) -> str:
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def _row_line(r: Row) -> str:
    return "| " + " | ".join(_cell(c) for c in (r.command, r.params, r.purpose, r.recipes, r.verified)) + " |"


def split_cells(line: str) -> list[str]:
    """`| a | b \\| c |` → ["a", "b | c"]。`\\|` は区切りではない。"""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells, cur, i = [], [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def parse(text: str) -> Ledger:
    lines = text.rstrip("\n").split("\n") if text else []
    start = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("|") and "コマンド" in ln), None)
    if start is None:
        return Ledger(lines, [], [], has_table=False)
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    header = split_cells(lines[start])
    index = {key: next((j for j, h in enumerate(header) if h.startswith(name)), None) for key, name in _KEYS.items()}
    has_sep = start + 1 < end and set(lines[start + 1].replace("|", "").strip()) <= set("-: ")
    sep = lines[start + 1] if has_sep else _SEP
    first = start + 2 if has_sep else start + 1
    rows = []
    for ln in lines[first:end]:
        cells = split_cells(ln)
        get = lambda k: cells[index[k]] if index[k] is not None and index[k] < len(cells) else ""  # noqa: E731
        if get("command"):
            rows.append(Row(get("command"), get("params"), get("purpose"), get("recipes"), get("verified")))
    # 4 列の古い表は、5 列に直すので区切り行も作り直す
    if len(header) != len(HEADER):
        sep = _SEP
    return Ledger(lines[:start], rows, lines[end:], sep)


def load(path: Path) -> Ledger:
    return parse(path.read_text(encoding="utf-8") if path.is_file() else "")


def save(path: Path, ledger: Ledger) -> None:
    text = ledger.render()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# ---- 収集 ------------------------------------------------------------------------


@dataclass
class Collected:
    rows: list[Row]
    added: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)  # どのレシピからも使われなくなった行


def _compact(params: dict) -> str:
    return json.dumps(params, ensure_ascii=False, separators=(",", ":")) if params else "{}"


def collect(rows: list[Row], recs: list[recipes.Recipe], registry: dict[str, photocraft.Command] | None = None) -> Collected:
    """レシピで使っているコマンドを台帳に反映する（requirements FR-08「レシピから自動収集」）。

    - 台帳にない使用コマンドは行を足す。params 例は最初に見つかった使用例、用途はコマンドの表示名とメニュー。
    - 「使用レシピ」は実際の使用に合わせて更新する。手で書いた用途・params 例・検証日は変えない。
    - レシピで使われなくなった行は消さず、使用レシピを空にして知らせる。
    """
    uses: dict[str, tuple[set[str], dict]] = {}
    for r in recs:
        for s in recipes.validate(r.text).steps:
            names, example = uses.setdefault(s.command, (set(), s.params))
            names.add(r.name)
    by_cmd = {r.command: r for r in rows}
    out: list[Row] = []
    added: list[str] = []
    unused: list[str] = []
    for r in rows:
        names = sorted(uses[r.command][0]) if r.command in uses else []
        # 手動で書いたレシピ名（レシピ以外の用途。例: "smoke 入力生成"）は、レシピに無くても残す
        manual = [n.strip() for n in r.recipes.split(",") if n.strip() and n.strip() not in {x.name for x in recs}]
        merged = ", ".join(sorted(set(names)) + [m for m in manual if m not in names])
        if r.command not in uses and not manual and r.recipes:
            unused.append(r.command)
        out.append(replace(r, recipes=merged))
    for cmd, (names, example) in uses.items():
        if cmd in by_cmd:
            continue
        info = registry.get(cmd) if registry else None
        purpose = f"{info.label}（{info.menu}）" if info and info.label else ""
        out.append(Row(cmd, _compact(example), purpose, ", ".join(sorted(names)), ""))
        added.append(cmd)
    return Collected(out, added, unused)


def missing_in(rows: list[Row], registry: dict[str, photocraft.Command]) -> list[str]:
    """台帳にあるが、使用バージョンのコマンド一覧にないコマンド。"""
    return [r.command for r in rows if r.command not in registry]


# ---- 検証日 ----------------------------------------------------------------------

_VER = re.compile(r"^v?\d+\.\d+\.\d+")


def successes(runs: list[dict]) -> dict[str, dict[str, str]]:
    """履歴から、レシピごとに「版 → 最後に成功した日」を取る。成功 = 失敗 0 件かつ 1 件以上成功。"""
    out: dict[str, dict[str, str]] = {}
    for r in runs:
        if r["status"] == "succeeded" and r["failed"] == 0 and r["ok"] > 0:
            day = r["started_at"][:10]
            cur = out.setdefault(r["recipe"], {})
            if cur.get(r["tag"], "") < day:
                cur[r["tag"]] = day
    return out


def _version_key(tag: str) -> tuple:
    nums = re.findall(r"\d+", tag)
    return tuple(int(n) for n in nums[:3])


def with_verified(rows: list[Row], ok: dict[str, dict[str, str]]) -> tuple[list[Row], list[str]]:
    """使用レシピの成功実行から検証日を更新する。変えた行のコマンドも返す。

    使用レシピのうち 1 つでも成功していれば、その版と日付を載せる（新しい日付と版一覧）。
    """
    out, changed = [], []
    for r in rows:
        names = [n.strip() for n in r.recipes.split(",") if n.strip()]
        per_tag: dict[str, str] = {}
        for n in names:
            for tag, day in ok.get(n, {}).items():
                if per_tag.get(tag, "") < day:
                    per_tag[tag] = day
        if not per_tag:
            out.append(r)
            continue
        latest = max(per_tag.values())
        tags = sorted(per_tag, key=_version_key)
        new = f"{latest} ({', '.join(tags)})"
        if new != r.verified:
            changed.append(r.command)
        out.append(replace(r, verified=new))
    return out, changed
