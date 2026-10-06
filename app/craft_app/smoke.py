"""スモークテスト（requirements.md FR-04）。scripts/smoke.sh・smoke.yml と同じ判定をアプリで行う。

全レシピを samples/smoke/in に pinned と latest の両方で適用し、出力ができるかを見る。
pinned 成功・latest 失敗なら「破壊的変更」（docs/upstream-tracking.md の判定ルール）。
CLI は params を検証しないため、成功しても params が効いているとは限らない（FR-04 の限界）。
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import recipes
from .jobs import Job, JobManager
from .paths import Repo
from .releases import Installed

COMPATIBLE = "互換"
BREAKING = "破壊的変更"
PINNED_FAILS = "ピン版で失敗"
BOTH_FAIL = "両版で失敗"
OK = "成功"
NG = "失敗"


def job_ok(job: Job) -> bool:
    """smoke.sh と同じ: batch が成功し、全入力の出力ができた。"""
    return job.status == "succeeded" and job.expected > 0 and len(job.ok) == job.expected


def recipe_verdict(pinned_ok: bool, latest_ok: bool | None) -> str:
    """1 レシピの判定。latest が None はピンが最新（比較なし）。"""
    if latest_ok is None:
        return OK if pinned_ok else NG
    if pinned_ok:
        return COMPATIBLE if latest_ok else BREAKING
    return PINNED_FAILS if latest_ok else BOTH_FAIL


def overall(verdicts: list[str]) -> str:
    if not verdicts:
        return "レシピなし"
    if BREAKING in verdicts:
        return BREAKING
    if all(v == COMPATIBLE for v in verdicts):
        return "互換（ピンを更新してよい）"
    if all(v == OK for v in verdicts):
        return "成功（ピンが最新）"
    return "要確認"


@dataclass
class SmokeRun:
    id: str
    pinned: Installed
    latest: Installed | None  # ピンが最新なら None
    jobs: dict[tuple[str, str], str] = field(default_factory=dict)  # (版, レシピ名) → ジョブ ID
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
    finished_at: str = ""
    verdict: str = ""

    @property
    def tags(self) -> list[str]:
        return [self.pinned.tag] + ([self.latest.tag] if self.latest else [])

    @property
    def recipe_names(self) -> list[str]:
        return sorted({r for _, r in self.jobs})

    def table(self, manager: JobManager) -> list[dict]:
        """レシピごとの結果と判定（画面と履歴に使う）。"""
        rows = []
        for name in self.recipe_names:
            got = {t: manager.jobs.get(self.jobs[(t, name)]) for t in self.tags}
            if any(j is None or not j.done for j in got.values()):
                rows.append({"レシピ": name, **{t: "実行中" for t in self.tags}, "判定": ""})
                continue
            ok = {t: job_ok(j) for t, j in got.items()}
            latest_ok = ok[self.latest.tag] if self.latest else None
            rows.append({"レシピ": name, **{t: OK if ok[t] else NG for t in self.tags}, "判定": recipe_verdict(ok[self.pinned.tag], latest_ok)})
        return rows

    def done(self, manager: JobManager) -> bool:
        return all(manager.jobs[j].done for j in self.jobs.values())


def start(manager: JobManager, repo: Repo, pinned: Installed, latest: Installed | None, versions: dict[str, str]) -> SmokeRun:
    """全レシピ × 版のジョブを同時に始め、終わったら判定を履歴に残す。

    versions は {tag: --version の出力}。出力先は out/smoke/<版>/<レシピ>（.gitignore 済み）。
    """
    if latest is not None and latest.tag == pinned.tag:
        latest = None
    run = SmokeRun(uuid.uuid4().hex[:12], pinned, latest)
    in_dir = repo.root / "samples" / "smoke" / "in"
    for inst in [pinned] + ([latest] if latest else []):
        for r in recipes.list_recipes(repo.actions_dir):
            out = repo.root / "out" / "smoke" / inst.tag / r.name
            shutil.rmtree(out, ignore_errors=True)  # 前回の出力で成功と誤判定しない
            job = manager.start_batch(inst.cli, inst.tag, versions.get(inst.tag, ""), r.path, r.hash, in_dir, out,
                                      kind="smoke", group=run.id)
            run.jobs[(inst.tag, r.name)] = job.id
    threading.Thread(target=_finish, args=(manager, run), daemon=True).start()
    return run


def _finish(manager: JobManager, run: SmokeRun) -> None:
    while not run.done(manager):
        time.sleep(0.2)
    rows = run.table(manager)
    verdict = overall([r["判定"] for r in rows])
    finished = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    manager.history.record_smoke(run.id, run.started_at, finished, run.pinned.tag,
                                 run.latest.tag if run.latest else "", verdict, json.dumps(rows, ensure_ascii=False))
    run.finished_at = finished
    run.verdict = verdict  # 履歴に残してから公開する（画面は verdict を完了の印に使う）
