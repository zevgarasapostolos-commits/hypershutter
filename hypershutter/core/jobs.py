"""A persistent background job queue for proxies and exports (thesis §6.2, §6.10).

Jobs live in SQLite in Application Support, so a crash or a restart loses nothing: running jobs
go back to the queue and their partial outputs are written again. Workers run ffmpeg at
background priority (macOS `taskpolicy -b`: throttled CPU and disk), so ingest and the app stay
responsive. The queue can be paused and resumed.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hypershutter.core import config

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"


@dataclass
class Job:
    id: int
    kind: str            # proxy | export
    project: str         # event folder
    rel: str             # source clip, relative to the project
    preset: str
    out: str             # output file
    status: str
    error: str = ""
    progress: float = 0.0
    created: float = 0.0
    started: float = 0.0
    finished: float = 0.0
    bytes_out: int = 0
    meta: str = ""       # JSON: what the runner needs besides the paths (e.g. the clip length)


def _db(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(str(path or config.app_support_dir() / "jobs.db"), timeout=30, check_same_thread=False)
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, kind TEXT, project TEXT, rel TEXT,
                  preset TEXT, out TEXT, status TEXT, error TEXT DEFAULT '', progress REAL DEFAULT 0,
                  created REAL, started REAL DEFAULT 0, finished REAL DEFAULT 0, bytes_out INTEGER DEFAULT 0)""")
    db.execute("CREATE INDEX IF NOT EXISTS jobs_out ON jobs(out)")
    if "meta" not in [r[1] for r in db.execute("PRAGMA table_info(jobs)")]:
        db.execute("ALTER TABLE jobs ADD COLUMN meta TEXT DEFAULT ''")
    return db


def read_all(db_path: Path | None = None) -> list[Job]:
    """Every job, without touching the queue (for drive monitoring and status views)."""
    db = _db(db_path)
    try:
        return [Job(*r) for r in db.execute("SELECT * FROM jobs ORDER BY id").fetchall()]
    finally:
        db.close()


Runner = Callable[[Job, Callable[[float], None]], int]      # returns the output size in bytes


class JobQueue:
    def __init__(self, runners: dict[str, Runner], workers: int = 1, db_path: Path | None = None):
        self.runners = runners
        self.workers = workers
        self._db = _db(db_path)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._idle = threading.Condition(self._lock)
        self._busy = 0
        with self._lock:                       # a job that was running when the app stopped runs again
            self._db.execute("UPDATE jobs SET status=?, progress=0 WHERE status=?", (QUEUED, RUNNING))
            self._db.commit()

    # ---------- queue ----------

    def add(self, kind: str, project: str, rel: str, preset: str, out: str, meta: str = "") -> int | None:
        """Queue a job unless the same output is already queued, running or done."""
        with self._lock:
            row = self._db.execute("SELECT id, status FROM jobs WHERE out=? AND kind=? ORDER BY id DESC LIMIT 1",
                                   (out, kind)).fetchone()
            if row and row[1] in (QUEUED, RUNNING, DONE) and (row[1] != DONE or Path(out).exists()):
                return None
            cur = self._db.execute("INSERT INTO jobs (kind, project, rel, preset, out, status, created, meta) "
                                   "VALUES (?,?,?,?,?,?,?,?)", (kind, project, rel, preset, out, QUEUED, time.time(), meta))
            self._db.commit()
            self._idle.notify_all()
            return cur.lastrowid

    def jobs(self, kind: str | None = None, project: str | None = None) -> list[Job]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if project:
            q += " AND project=?"
            args.append(project)
        with self._lock:
            rows = self._db.execute(q + " ORDER BY id", args).fetchall()
        return [Job(*r) for r in rows]

    def counts(self, kind: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for j in self.jobs(kind):
            out[j.status] = out.get(j.status, 0) + 1
        return out

    def cancel(self, job_id: int) -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET status=? WHERE id=? AND status=?", (CANCELLED, job_id, QUEUED))
            self._db.commit()

    def retry_failed(self, kind: str | None = None) -> None:
        with self._lock:
            self._db.execute("UPDATE jobs SET status=?, error='' WHERE status=?" + (" AND kind=?" if kind else ""),
                             (QUEUED, FAILED, kind) if kind else (QUEUED, FAILED))
            self._db.commit()
            self._idle.notify_all()

    # ---------- workers ----------

    def _next(self) -> Job | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE status=? AND kind IN (%s) ORDER BY id LIMIT 1"
                                   % ",".join("?" * len(self.runners)), (QUEUED, *self.runners)).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE jobs SET status=?, started=? WHERE id=?", (RUNNING, time.time(), row[0]))
            self._db.commit()
            self._busy += 1
            return Job(*row)

    def _set(self, job_id: int, **fields) -> None:
        with self._lock:
            sets = ", ".join(f"{k}=?" for k in fields)
            self._db.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
            self._db.commit()

    def run_one(self, job: Job) -> None:
        def progress(x: float) -> None:
            self._set(job.id, progress=round(min(max(x, 0.0), 1.0), 3))

        try:
            size = self.runners[job.kind](job, progress)
            self._set(job.id, status=DONE, progress=1.0, finished=time.time(), bytes_out=int(size or 0))
        except Exception as e:                  # one bad clip never stops the queue
            self._set(job.id, status=FAILED, error=str(e)[:500], finished=time.time())
        finally:
            with self._lock:
                self._busy -= 1
                self._idle.notify_all()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.3)
                continue
            job = self._next()
            if job is None:
                with self._lock:
                    self._idle.wait(timeout=1.0)
                continue
            self.run_one(job)

    def start(self) -> None:
        self._stop.clear()
        self._threads = [threading.Thread(target=self._loop, daemon=True) for _ in range(self.workers)]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._idle.notify_all()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def wait(self, kind: str | None = None, timeout: float | None = None) -> bool:
        """Until no job of `kind` is queued or running (True), or the timeout passes (False)."""
        end = None if timeout is None else time.time() + timeout
        while True:
            c = self.counts(kind)
            if not c.get(QUEUED) and not c.get(RUNNING):
                return True
            if end is not None and time.time() > end:
                return False
            time.sleep(0.5)

    def drain(self) -> None:
        """Run every queued job of these runners in this thread (CLI, tests)."""
        while (job := self._next()) is not None:
            self.run_one(job)
