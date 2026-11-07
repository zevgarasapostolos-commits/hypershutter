"""Ingest: copy a memory card to several drives at once, verified by checksum (thesis §6.1).

- Read once, write many: each file is read from the card once, hashed (xxHash64) while it is read,
  and written to every destination in parallel (one writer thread per drive, bounded queues).
- Verify: every destination copy is read back from the drive (F_NOCACHE, so the check reads the
  disk and not the copy still in memory) and its hash compared with the card's. A mismatch is
  copied again (up to `retries` times) and then flagged.
- Resumable: files already verified on a destination (same path, size and hash in its manifest)
  are skipped, so a card can be inserted again or an interrupted ingest restarted.
- The card is only read. Copies get the card file's modification time. Nothing is overwritten:
  a different file already at the same place makes the card's file go to `<label>/<card>/`.
- A card is "safe to format" only when every file is verified on every destination; HyperShutter
  never formats or erases a card itself.
"""

from __future__ import annotations

import fcntl
import json
import os
import queue
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import xxhash

from hypershutter.core import cards, config, manifest
from hypershutter.core.cards import Card
from hypershutter.core.manifest import COPIED, FAILED, VERIFIED, Manifest

CHUNK = 8 << 20
QUEUE_DEPTH = 4
PART = ".hspart"
F_NOCACHE = getattr(fcntl, "F_NOCACHE", 48)
MARGIN_BYTES = 1 << 30
PROXY_RATIO = {"prores_proxy": 0.35, "h264": 0.06, "none": 0.0}   # proxy size / source size, rough

Progress = Callable[[dict], None]


@dataclass
class Job:
    src: Path
    card_rel: str
    rel: str                 # relative to the project folder on each destination: "<label>/<name>"
    size: int
    mtime: float
    xxh64: str = ""          # of the card file, once read

    @property
    def source(self) -> str:
        """The card file, as the manifest knows it: a second card whose camera counter started
        again (another C0001.MP4) has other modification times, so it never passes for this one."""
        return f"{self.card_rel}@{int(self.mtime)}"


@dataclass
class DestState:
    root: Path               # <drive>/<project>
    manifest: Manifest
    to_write: int = 0        # bytes this session must write here
    written: int = 0
    verified_bytes: int = 0
    copy_seconds: float = 0.0
    verify_seconds: float = 0.0
    failed: list[str] = field(default_factory=list)

    def status(self, t0: float) -> dict:
        el = max(time.time() - t0, 1e-6)
        rate = self.written / el
        left = max(self.to_write - self.written, 0)
        return {"root": str(self.root), "written": self.written, "total": self.to_write,
                "mb_s": round(rate / 1e6, 1), "eta_s": round(left / rate) if rate > 0 else None}


@dataclass
class Report:
    session: str
    card: dict
    project: str
    label: str
    dests: list[dict]
    files: int
    bytes: int
    copied: int
    skipped: int
    failed: list[dict]
    safe_to_format: bool
    seconds: float


def _nocache(fd: int) -> None:
    try:
        fcntl.fcntl(fd, F_NOCACHE, 1)
    except OSError:
        pass


def hash_file(path: Path, nocache: bool = True) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        if nocache:
            _nocache(f.fileno())
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _inside(a: Path, b: Path) -> bool:
    try:
        a.resolve().relative_to(b.resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------- planning ----------------

def plan(card: Card, label: str) -> list[Job]:
    """Files of the card under `<label>/`, flat (camera folders like PRIVATE/M4ROOT/CLIP or
    DCIM/100MEDIA are dropped) unless two files share a name, which then keep their card folders."""
    names = Counter(Path(f.rel).name for f in card.files)
    return [Job(Path(card.path) / f.rel, f.rel,
                f"{label}/{Path(f.rel).name}" if names[Path(f.rel).name] == 1 else f"{label}/{f.rel}", f.size, f.mtime)
            for f in card.files]


def _volume_key(path: Path) -> int:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return p.stat().st_dev


def _free(path: Path) -> int:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def check(card: Card, jobs: list[Job], dests: list[Path], project: str, proxy: str = "prores_proxy") -> dict:
    """The pre-flight in detail: what blocks the ingest (codes the app can translate), what each
    drive must hold (card data not yet there + proxies on the first destination + a margin, per
    physical drive) and how much it has free."""
    problems: list[dict] = []
    need: dict[int, int] = {}
    free: dict[int, int] = {}
    where: dict[int, str] = {}
    card_bytes = sum(j.size for j in jobs)
    proxy_bytes = int(card_bytes * PROXY_RATIO.get(proxy, 0.35))
    drives = []
    for k, d in enumerate(dests):
        d = Path(d)
        if _inside(d, Path(card.path)) or _inside(Path(card.path), d):
            problems.append({"code": "on_card", "path": str(d)})
            continue
        p = d
        while not p.exists():
            p = p.parent
        if not os.access(p, os.W_OK):
            problems.append({"code": "not_writable", "path": str(d)})
            continue
        m = Manifest(d / project)
        missing = sum(j.size for j in jobs if not m.verified(j.rel, j.size))
        if k == 0:
            missing += proxy_bytes
        key = _volume_key(d)
        need[key] = need.get(key, 0) + missing
        free[key] = _free(d)
        where.setdefault(key, str(d))
        drives.append({"path": str(d), "free_gb": round(_free(d) / 1e9, 1)})
    for key, n in need.items():
        total = n + (MARGIN_BYTES + n // 100 if n else 0)
        if total > free[key]:
            problems.append({"code": "space", "path": where[key], "need_gb": round(total / 1e9, 1),
                             "free_gb": round(free[key] / 1e9, 1)})
    with_proxies = card_bytes + proxy_bytes
    margin = MARGIN_BYTES + with_proxies // 100                 # the same rule as the space check above
    bare_margin = MARGIN_BYTES + card_bytes // 100
    return {"problems": problems, "drives": drives, "card_gb": round(card_bytes / 1e9, 1),
            "proxies_gb": round(proxy_bytes / 1e9, 1), "margin_gb": round(margin / 1e9, 1),
            "without_proxies_gb": round((card_bytes + bare_margin) / 1e9, 1)}


def preflight(card: Card, jobs: list[Job], dests: list[Path], project: str, proxy: str = "prores_proxy") -> list[str]:
    """Problems that block the ingest, as English sentences (CLI, errors)."""
    text = {"on_card": "{path}: a destination cannot be on the card", "not_writable": "{path}: not writable",
            "space": "{path}: needs {need_gb:.1f} GB, only {free_gb:.1f} GB free"}
    return [text[p["code"]].format(**p) for p in check(card, jobs, dests, project, proxy)["problems"]]


def _resolve_conflicts(card: Card, jobs: list[Job], states: list[DestState]) -> int:
    """A different file already at a job's place on any destination sends that job to
    `<label>/<card name>/…` on every destination (destinations stay identical). Returns how many moved."""
    moved = 0
    for j in jobs:
        rel = j.rel
        k = 1
        while True:
            clash = False
            for s in states:
                e = s.manifest.get(rel)
                f = s.root / rel
                if e is not None and (e.source != j.source or e.size != j.size):
                    clash = True
                elif e is None and f.exists() and f.stat().st_size != j.size:
                    clash = True
            if not clash:
                break
            label, name = j.rel.split("/", 1)[0], Path(j.rel).name
            rel = f"{label}/{card.name}{'' if k == 1 else f'-{k}'}/{name}"
            k += 1
        if rel != j.rel:
            j.rel = rel
            moved += 1
    return moved


# ---------------- copy and verify ----------------

def _copy(job: Job, targets: list[tuple[DestState, Path]], on_bytes: Callable[[DestState, int], None],
          corrupt: Callable[[Path], None] | None = None) -> str:
    """Read the card file once, write it to every target in parallel; returns the card file's hash."""
    h = xxhash.xxh64()
    queues = [queue.Queue(QUEUE_DEPTH) for _ in targets]
    errors: dict[int, BaseException] = {}
    temps = [t.parent / f".{t.name}{PART}" for _, t in targets]

    def writer(i: int) -> None:
        state, _ = targets[i]
        try:
            temps[i].parent.mkdir(parents=True, exist_ok=True)
            with open(temps[i], "wb") as f:
                _nocache(f.fileno())
                while (chunk := queues[i].get()) is not None:
                    f.write(chunk)
                    on_bytes(state, len(chunk))
                f.flush()
                os.fsync(f.fileno())
        except BaseException as e:                       # the drive failed or is full: this target fails
            errors[i] = e
            while queues[i].get() is not None:           # keep draining so the reader never blocks
                pass

    threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(len(targets))]
    for t in threads:
        t.start()
    try:
        with open(job.src, "rb") as src:
            _nocache(src.fileno())
            while chunk := src.read(CHUNK):
                h.update(chunk)
                for q in queues:
                    q.put(chunk)
    finally:
        for q in queues:
            q.put(None)
        for t in threads:
            t.join()
    for i, (state, target) in enumerate(targets):
        if i in errors:
            state.failed.append(f"{job.rel}: {errors[i]}")
            continue
        os.utime(temps[i], (time.time(), job.mtime))
        if target.exists():                              # an unverified earlier copy: kept aside, never deleted
            target.rename(target.with_name(f".{target.name}.hs-old-{int(time.time())}"))
        temps[i].rename(target)
        if corrupt:
            corrupt(target)
    return h.hexdigest()


def ingest(card: Card, project: str, label: str, dests: list[Path], proxy: str = "prores_proxy",
           retries: int = 2, progress: Progress | None = None,
           on_verified: Callable[[Path, str], None] | None = None,
           _corrupt: Callable[[Path], None] | None = None) -> Report:
    """Copy and verify every file of the card to `<dest>/<project>/<label>/` on every destination.
    `on_verified(project folder, rel)` fires for each file verified on the first destination
    (the proxy queue listens there). `_corrupt` is a test hook that damages a copy after writing."""
    if not label.strip() or "/" in label:
        raise ValueError("the source label must be a plain folder name, e.g. 'cam apos'")
    if not dests:
        raise ValueError("choose at least one destination drive")
    jobs = plan(card, label.strip())
    problems = preflight(card, jobs, dests, project, proxy)
    if problems:
        raise OSError("; ".join(problems))
    cards.remember(card.identity, label.strip())
    from hypershutter.core import execute
    execute.remember_copies([Path(d) / project for d in dests])
    started = datetime.now()
    session = started.strftime("%Y%m%d-%H%M%S")
    t0 = time.time()
    states = [DestState(Path(d) / project, Manifest(Path(d) / project)) for d in dests]
    _resolve_conflicts(card, jobs, states)
    lock = threading.Lock()
    current = {"phase": "copy", "done": 0, "total": 0, "file": "", "last": 0.0}

    def emit(phase: str, done: int, total: int, file: str = "") -> None:
        current.update(phase=phase, done=done, total=total, file=file, last=time.time())
        if progress:
            progress({"phase": phase, "done": done, "total": total, "file": file,
                      "dests": [s.status(t0) for s in states]})

    def on_bytes(state: DestState, n: int) -> None:
        with lock:
            state.written += n
            due = time.time() - current["last"] >= 0.5
        if due:                                          # live MB/s and ETA while a long clip copies
            emit(current["phase"], current["done"], current["total"], current["file"])

    # 1. copy what is not yet verified on each destination
    todo: list[tuple[Job, list[DestState]]] = []
    for j in jobs:
        need = [s for s in states if not s.manifest.verified(j.rel, j.size)]
        if on_verified and states[0] not in need:        # verified in an earlier session: proxy if missing
            on_verified(states[0].root, j.rel)
        if need:
            todo.append((j, need))
            for s in need:
                s.to_write += j.size
        else:
            j.xxh64 = states[0].manifest.get(j.rel).xxh64
    skipped = len(jobs) - len(todo)
    for k, (j, need) in enumerate(todo, start=1):
        emit("copy", k - 1, len(todo), j.rel)
        targets = [(s, s.root / j.rel) for s in need]
        tc = time.time()
        j.xxh64 = _copy(j, targets, on_bytes, _corrupt)
        for s in need:
            s.copy_seconds += time.time() - tc
            if not any(f.startswith(f"{j.rel}:") for f in s.failed):
                s.manifest.set(j.rel, j.size, j.xxh64, COPIED, j.source)
        if k % 20 == 0:
            for s in states:
                s.manifest.save()
    for s in states:
        s.manifest.save()
    emit("copy", len(todo), len(todo))

    # 2. verify every copy that is not verified yet, all drives in parallel
    def verify(s: DestState) -> list[Job]:
        bad = []
        tv = time.time()
        for j, need in todo:
            e = s.manifest.get(j.rel)
            if not any(x is s for x in need) or e is None or e.status != COPIED:
                continue
            ok = hash_file(s.root / j.rel) == j.xxh64
            s.manifest.set(j.rel, j.size, j.xxh64, VERIFIED if ok else FAILED, j.source)
            if ok:
                s.verified_bytes += j.size
                if on_verified and s is states[0]:
                    on_verified(s.root, j.rel)
            else:
                bad.append(j)
        s.verify_seconds += time.time() - tv
        s.manifest.save()
        return bad

    emit("verify", 0, len(states))
    with ThreadPoolExecutor(max_workers=len(states)) as ex:
        bad = dict(zip(range(len(states)), ex.map(verify, states)))

    # 3. retry mismatches: copy again from the card, verify again
    for attempt in range(retries):
        pending = [(i, j) for i, js in bad.items() for j in js]
        if not pending:
            break
        emit("retry", attempt + 1, retries)
        bad = {}
        for i, j in pending:
            s = states[i]
            before = j.xxh64
            j.xxh64 = _copy(j, [(s, s.root / j.rel)], on_bytes, _corrupt)
            if j.xxh64 != before:                        # the card itself read differently: do not trust it
                s.failed.append(f"{j.rel}: the card file read differently twice")
            ok = j.xxh64 == before and hash_file(s.root / j.rel) == j.xxh64
            s.manifest.set(j.rel, j.size, j.xxh64, VERIFIED if ok else FAILED, j.source)
            if ok and on_verified and s is states[0]:
                on_verified(s.root, j.rel)
            if not ok:
                bad.setdefault(i, []).append(j)
        for s in states:
            s.manifest.save()

    # 4. reports: per destination JSON + MHL, and the overall verdict
    failed = []
    for s in states:
        for j in jobs:
            if not s.manifest.verified(j.rel, j.size):
                why = next((f.split(": ", 1)[1] for f in s.failed if f.startswith(j.rel + ": ")), "checksum mismatch")
                failed.append({"dest": str(s.root), "file": j.rel, "why": why})
    safe = not failed
    finished = datetime.now()
    total = sum(j.size for j in jobs)
    report = Report(session, {"name": card.name, "kind": card.kind, "identity": card.identity, "camera": card.camera,
                              "path": card.path}, project, label, [], len(jobs), total, len(todo), skipped, failed, safe,
                    round(time.time() - t0, 1))
    for s in states:
        entries = [s.manifest.get(j.rel) for j in jobs if s.manifest.get(j.rel)]
        mhl = manifest.write_mhl(s.root / label / f"{label}_{session}.mhl", s.root, entries, started, finished)
        d = {"root": str(s.root), "written": s.written, "copy_s": round(s.copy_seconds, 1),
             "verify_s": round(s.verify_seconds, 1),
             "write_mb_s": round(s.written / s.copy_seconds / 1e6, 1) if s.copy_seconds else None,
             "verify_mb_s": round(s.verified_bytes / s.verify_seconds / 1e6, 1) if s.verify_seconds else None,
             "verified": sum(1 for e in entries if e.status == VERIFIED), "mhl": str(mhl)}
        report.dests.append(d)
    for s in states:
        out = s.root / ".hypershutter" / "ingest" / f"{session}-{label}.json"
        out.write_text(json.dumps({**asdict(report), "files_detail": [asdict(e) for e in
                                   (s.manifest.get(j.rel) for j in jobs) if e]}, ensure_ascii=False, indent=1))
    history = config.app_support_dir() / "ingest"
    history.mkdir(exist_ok=True)
    (history / f"{session}-{label}.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=1))
    emit("done", 1, 1)
    return report
