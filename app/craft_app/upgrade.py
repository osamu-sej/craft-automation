"""アップグレード手順ウィザード（requirements.md FR-06）。docs/upstream-tracking.md の「更新時の手順」を機械的に守らせる。

1. 差分確認   … 監視対象ファイルの変更を確認済みにし、差分・リリースを確認した
2. スモーク   … ピン版 → 更新先の版で、今のレシピ全体がすべて成功した（破壊的変更なし）
3. 修正の確認 … レシピと docs/commands.md の見直しを終えた
4. 記録       … ピン（.photocraft-version）を更新し、docs/upgrade-log.md に追記する

4 つがそろわないとピンを更新できない（スキップ不可）。判定は画面ではなくここで行い、`apply` でも再確認する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from . import recipes
from .paths import Repo


class GateError(RuntimeError):
    pass


@dataclass
class Gates:
    pinned: str
    target: str
    reviewed: bool  # 手順 1 の確認チェック
    watched_pending: int  # まだ記録していない監視対象の数
    watched_unknown: int  # 本家で取得できなかった監視対象の数
    smoke_ok: bool
    smoke_reason: str
    step3_done: bool  # 手順 3 の確認チェック
    notes: list[str] = field(default_factory=list)

    @property
    def step1(self) -> bool:
        return self.reviewed and self.watched_pending == 0 and self.watched_unknown == 0

    @property
    def ready(self) -> bool:
        return self.step1 and self.smoke_ok and self.step3_done and self.target != self.pinned

    def blockers(self) -> list[str]:
        out = []
        if self.target == self.pinned:
            out.append("更新先がピンと同じです")
        if self.watched_unknown:
            out.append(f"本家で取得できなかった監視対象が {self.watched_unknown} 件あります（再確認してください）")
        if self.watched_pending:
            out.append(f"確認済みにしていない監視対象が {self.watched_pending} 件あります")
        if not self.reviewed:
            out.append("手順 1: 差分とリリースの確認が済んでいません")
        if not self.smoke_ok:
            out.append(f"手順 2: {self.smoke_reason}")
        if not self.step3_done:
            out.append("手順 3: レシピと docs/commands.md の見直しが済んでいません")
        return out


def smoke_gate(row: dict | None, recipes_hash: str, pinned: str, target: str) -> tuple[bool, str]:
    """スモークの結果が、今のレシピ全体に対して「互換」か。"""
    if row is None:
        return False, f"{pinned} → {target} のスモークテストがまだありません"
    if not row["verdict"].startswith("互換"):
        return False, f"スモークテストの結果が「{row['verdict']}」です。レシピを直して再実行してください"
    if row["recipes_hash"] != recipes_hash:
        return False, "スモークテストのあとにレシピが変わりました。もう一度実行してください"
    return True, "互換"


def evaluate(pinned: str, target: str, *, reviewed: bool, step3_done: bool, watched, smoke_row: dict | None, recipes_hash: str) -> Gates:
    """watched は upstream.Watched の列（記録 SHA を読み直したもの）。None は本家をまだ確認していない。"""
    if watched is None:
        pending, unknown, notes = 0, 1, ["本家をまだ確認していません"]
    else:
        pending = sum(1 for w in watched if w.pending)  # 変更あり・未記録（取得失敗は pending ではなく unknown）
        unknown = sum(1 for w in watched if w.latest is None)
        notes = []
    ok, why = smoke_gate(smoke_row, recipes_hash, pinned, target)
    return Gates(pinned, target, reviewed, pending, unknown, ok, why, step3_done, notes)


# ---- 記録 ----------------------------------------------------------------------------

LOG_HEADER = "# アップグレード履歴\n\n| 日付 | from | to | 結果 | 修正内容 |\n|---|---|---|---|---|\n"


def _cell(s: str) -> str:
    return " ".join(s.replace("\r", " ").replace("\n", " ").split()).replace("|", "\\|")


def append_log(text: str, day: str, frm: str, to: str, result: str, fix: str) -> str:
    """upgrade-log.md の表の最後に 1 行足した全文を返す。表がなければ作る。"""
    row = f"| {day} | {_cell(frm)} | {_cell(to)} | {_cell(result)} | {_cell(fix)} |"
    if not text.strip():
        return LOG_HEADER + row + "\n"
    lines = text.rstrip("\n").split("\n")
    last = max((i for i, ln in enumerate(lines) if ln.lstrip().startswith("|")), default=None)
    if last is None:
        return text.rstrip("\n") + "\n\n" + LOG_HEADER.split("\n\n", 1)[1] + row + "\n"
    lines.insert(last + 1, row)
    return "\n".join(lines) + "\n"


@dataclass
class Applied:
    changed: list[str]  # 変更したファイル（リポジトリ基準）


def apply(repo: Repo, gates: Gates, *, result: str, fix: str, mark_tested: bool = True,
          make_snapshot: Callable[[], Path] | None = None, today: str | None = None) -> Applied:
    """ゲートをすべて満たしているときだけ、スナップショット → tested_with → 履歴 → ピンの順に書く。

    ピンは最後に書く。途中で失敗したら、ピンは変わらない。
    """
    if not gates.ready:
        raise GateError("ピンを更新できません: " + " / ".join(gates.blockers()))
    current = repo.pinned()
    if current != gates.pinned:
        raise GateError(f"ピンが {gates.pinned} から {current} に変わっています。画面を開き直してください")
    day = today or date.today().isoformat()
    changed: list[str] = []
    if make_snapshot is not None:
        changed.append(make_snapshot().relative_to(repo.root).as_posix() + "/")
    if mark_tested:
        for r in recipes.list_recipes(repo.actions_dir):
            recipes.mark_tested(r.path, gates.target)
            changed.append(r.path.relative_to(repo.root).as_posix())
    log = repo.root / "docs" / "upgrade-log.md"
    old = log.read_text(encoding="utf-8") if log.is_file() else ""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(append_log(old, day, gates.pinned, gates.target, result, fix), encoding="utf-8", newline="\n")
    changed.append("docs/upgrade-log.md")
    repo.pin_file.write_text(gates.target + "\n", encoding="utf-8", newline="\n")
    changed.append(".photocraft-version")
    return Applied(changed)
