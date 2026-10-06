"""batch のバックグラウンド実行と実行履歴（requirements.md FR-03、§4 再現性・可観測性）。

UI をブロックしないよう、CLI はスレッドで動かし、画面は状態を定期的に読む。
履歴には「使用版・レシピ内容ハッシュ・入出力パス・実行コマンド全文・終了コード・ログ」を残す。
"""

from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import photocraft


def kill_tree(proc: subprocess.Popen) -> None:
    """プロセスを止める。Windows は子プロセスごと（.bat 経由の起動に備える）。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    args: list[str]
    recipe: str
    recipe_hash: str
    tag: str
    version: str  # --version の出力
    in_dir: str
    out_dir: str
    expected: int  # 処理予定の入力数
    kind: str = "batch"  # batch / smoke
    group: str = ""  # スモークテスト1回分のジョブをまとめる ID
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    status: str = "running"  # running / succeeded / failed / cancelled / error
    exit_code: int | None = None
    log: list[tuple[str, str]] = field(default_factory=list)  # (stream, line)
    ok: list[tuple[str, str]] = field(default_factory=list)  # (入力, 出力)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (入力, 理由)
    warnings: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def command(self) -> str:
        """実行コマンド全文（その OS のシェルにそのまま貼れる形）。"""
        return subprocess.list2cmdline(self.args) if os.name == "nt" else shlex.join(self.args)

    @property
    def done(self) -> bool:
        return self.status != "running"

    def log_text(self) -> str:
        with self._lock:
            return "\n".join(f"[{s}] {line}" for s, line in self.log)


class History:
    """実行履歴（SQLite）。スレッドごとに接続を開く。"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, recipe TEXT, recipe_hash TEXT, tag TEXT, version TEXT,
                    command TEXT, in_dir TEXT, out_dir TEXT, status TEXT, exit_code INTEGER,
                    ok INTEGER, failed INTEGER, log TEXT, started_at TEXT, finished_at TEXT)"""
            )
            cols = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
            if "kind" not in cols:  # P1 で作った履歴に列を足す
                c.execute("ALTER TABLE runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'batch'")
                c.execute("ALTER TABLE runs ADD COLUMN group_id TEXT NOT NULL DEFAULT ''")
            c.execute(
                """CREATE TABLE IF NOT EXISTS smokes(
                    id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, pinned TEXT, latest TEXT,
                    verdict TEXT, detail TEXT)"""
            )
            if "recipes_hash" not in {r["name"] for r in c.execute("PRAGMA table_info(smokes)")}:
                c.execute("ALTER TABLE smokes ADD COLUMN recipes_hash TEXT NOT NULL DEFAULT ''")  # P2 で作った履歴に足す

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def record(self, j: Job) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO runs(id, recipe, recipe_hash, tag, version, command, in_dir, out_dir, status,
                    exit_code, ok, failed, log, started_at, finished_at, kind, group_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (j.id, j.recipe, j.recipe_hash, j.tag, j.version, j.command, j.in_dir, j.out_dir, j.status,
                 j.exit_code, len(j.ok), len(j.failed), j.log_text(), j.started_at, j.finished_at, j.kind, j.group),
            )

    def runs(self, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]

    def last_by_recipe(self) -> dict[str, dict]:
        """レシピ名ごとの最終実行（FR-01 の「最終実行結果」。一括実行のみ）。"""
        out: dict[str, dict] = {}
        for r in self.runs(1000):
            if r["kind"] == "batch":
                out.setdefault(r["recipe"], r)
        return out

    def record_smoke(self, id: str, started_at: str, finished_at: str, pinned: str, latest: str, verdict: str, detail: str,
                     recipes_hash: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO smokes(id, started_at, finished_at, pinned, latest, verdict, detail, recipes_hash) VALUES (?,?,?,?,?,?,?,?)",
                      (id, started_at, finished_at, pinned, latest, verdict, detail, recipes_hash))

    def latest_smoke(self, pinned: str, latest: str) -> dict | None:
        """ピン版 → 最新版の組み合わせで、最後に実行したスモークテスト。"""
        with self._conn() as c:
            row = c.execute("SELECT * FROM smokes WHERE pinned=? AND latest=? ORDER BY started_at DESC LIMIT 1", (pinned, latest)).fetchone()
        return dict(row) if row else None

    def smokes(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM smokes ORDER BY started_at DESC LIMIT ?", (limit,))]


class JobManager:
    def __init__(self, history: History):
        self.history = history
        self.jobs: dict[str, Job] = {}

    def start_batch(self, cli: Path, tag: str, version: str, recipe: Path, recipe_hash: str,
                    in_dir: Path, out_dir: Path, fmt: str = "", quality: int | None = None,
                    kind: str = "batch", group: str = "") -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            args=photocraft.batch_args(cli, recipe, in_dir, out_dir, fmt, quality),
            recipe=recipe.stem, recipe_hash=recipe_hash, tag=tag, version=version,
            in_dir=str(in_dir), out_dir=str(out_dir), expected=len(photocraft.list_inputs(in_dir)),
            kind=kind, group=group,
        )
        self.jobs[job.id] = job
        try:
            job._proc = subprocess.Popen(
                job.args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            job.log.append(("app", f"起動できません: {e}"))
            self._finish(job, "error", None)
            return job
        readers = [threading.Thread(target=self._read, args=(job, job._proc.stdout, "stdout"), daemon=True),
                   threading.Thread(target=self._read, args=(job, job._proc.stderr, "stderr"), daemon=True)]
        for t in readers:
            t.start()
        threading.Thread(target=self._wait, args=(job, readers), daemon=True).start()
        return job

    def _read(self, job: Job, stream, name: str) -> None:
        for line in stream:
            line = line.rstrip("\r\n")
            parsed = photocraft.parse_batch_line(line)
            with job._lock:
                job.log.append((name, line))
                if parsed.kind == "ok":
                    job.ok.append((parsed.a, parsed.b))
                elif parsed.kind == "fail":
                    job.failed.append((parsed.a, parsed.b))
                elif parsed.kind == "warning":
                    job.warnings.append(parsed.a)

    def _wait(self, job: Job, readers: list[threading.Thread]) -> None:
        code = job._proc.wait()
        for t in readers:
            t.join()
        if job.cancel_requested:
            self._finish(job, "cancelled", code)
        else:
            self._finish(job, "succeeded" if code == 0 else "failed", code)

    def _finish(self, job: Job, status: str, code: int | None) -> None:
        job.exit_code = code
        job.finished_at = _now()
        job.status = status
        self.history.record(job)

    def cancel(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job and not job.done and job._proc:
            job.cancel_requested = True
            kill_tree(job._proc)
