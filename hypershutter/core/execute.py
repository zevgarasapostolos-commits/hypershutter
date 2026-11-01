"""Apply a reviewed structure: move every clip (with its sidecars) into its numbered folder, with undo.

Safety rules:
- the journal (every planned move) is written to Application Support and to
  <event>/.hypershutter/ BEFORE the first file moves;
- files are only renamed on the same drive (os.rename): never copied-and-deleted, never
  re-encoded, never deleted, and a move never overwrites an existing file;
- undo puts every file back at its exact original path and name, newest move first. It works
  from what is on disk, so it also recovers a run that stopped half way;
- the reference projects used for evaluation are refused outright.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from hypershutter.core import checks, config, store
from hypershutter.core.greeklish import safe_folder_name
from hypershutter.core.project import Project
from hypershutter.core.structure import Structure

READ_ONLY = ("073 Β11-10-2026 Γ", "gamos 25-07")       # reference projects for evaluation
NUMBERED = re.compile(r"^\d{2}[a-z]? ")
JOURNAL_DIR = ".hypershutter"
SAVE_EVERY = 25                                         # journal status updates during a run

Progress = Callable[[str, int, int], None]


@dataclass
class Move:
    src: str                  # paths relative to the event folder
    dst: str
    clip: str
    kind: str                 # clip | sidecar
    size: int
    status: str = "planned"   # planned | moved | undone | missing


@dataclass
class Plan:
    root: str
    moves: list[Move] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)       # folders that will be created
    in_place: int = 0
    conflicts: list[str] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)    # clips that stay where they are

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip()


def check_allowed(p: Project, force: bool = False) -> None:
    """Refuse the reference projects, and a project someone already organized by hand."""
    root = Path(p.root)
    if _nfc(root.name) in {_nfc(n) for n in READ_ONLY}:
        raise PermissionError(f"{root.name.strip()} is a read-only reference project")
    organized = sum(bool(NUMBERED.match(c.rel)) for c in p.clips.values())
    if organized > len(p.clips) // 2 and not journals(p) and not force:
        raise PermissionError("this event already looks organized by hand; refusing to move its files")


# ---------------- planning ----------------

def full_assignment(p: Project, st: Structure) -> dict[str, str]:
    """Video clips from the structure, plus audio files joined to the folder they overlap most in time."""
    out = dict(st.assignment)
    spans = []
    for cid, key in st.assignment.items():
        c = p.clips.get(cid)
        t = p.corrected(c) if c else None
        if t:
            spans.append((t, t + timedelta(seconds=c.duration), key))
    for c in p.clips.values():
        if c.kind != "audio" or c.id in out:
            continue
        t = p.corrected(c)
        if not t:
            continue
        end = t + timedelta(seconds=c.duration)
        overlap: dict[str, float] = {}
        for a, b, key in spans:
            s = (min(end, b) - max(t, a)).total_seconds()
            if s > 0:
                overlap[key] = overlap.get(key, 0) + s
        if overlap:
            out[c.id] = max(overlap, key=overlap.get)
    return out


def _new_stem(pattern: str, clip_stem: str, folder_number: str, n: int, t: datetime | None) -> str:
    stem = pattern.format(num=folder_number, n=n, name=clip_stem, time=f"{t:%H%M%S}" if t else "000000")
    stem = safe_folder_name(stem)
    if not stem or "/" in stem:
        raise ValueError(f"rename pattern gives an unusable name: {stem!r}")
    return stem


def plan(p: Project, st: Structure, rename: str | None = None) -> Plan:
    root = Path(p.root)
    pl = Plan(root=str(root))
    folder_of = {c.key: c.folder for c in st.categories}
    number_of = {c.key: f"{c.number:02d}{c.sub}" for c in st.categories}
    assign = full_assignment(p, st)
    taken: dict[str, str] = {}
    counters: dict[str, int] = {}
    order = sorted(assign, key=lambda cid: (p.corrected(p.clips[cid]) or datetime.min, cid))
    for cid in order:
        c = p.clips[cid]
        key = assign[cid]
        if key not in folder_of:
            pl.unassigned.append(cid)
            continue
        folder = folder_of[key]
        counters[key] = counters.get(key, 0) + 1
        stem, ext = os.path.splitext(c.name)
        new_stem = _new_stem(rename, stem, number_of[key], counters[key], p.corrected(c)) if rename else stem
        files = [(c.rel, "clip")] + [(s, "sidecar") for s in c.sidecars]
        for rel, kind in files:
            name = os.path.basename(rel)
            if new_stem != stem and name.startswith(stem):
                name = new_stem + name[len(stem):]
            dst = f"{folder}/{name}"
            if _nfc(dst) in taken:
                pl.conflicts.append(f"{dst}: two files would get this name ({taken[_nfc(dst)]} and {rel})")
                continue
            taken[_nfc(dst)] = rel
            if _nfc(rel) == _nfc(dst):
                pl.in_place += 1
                continue
            src_path, dst_path = root / rel, root / dst
            if not src_path.exists():
                pl.conflicts.append(f"{rel}: missing on disk")
                continue
            if dst_path.exists():
                pl.conflicts.append(f"{dst}: already exists, will not overwrite")
                continue
            pl.moves.append(Move(rel, dst, cid, kind, src_path.stat().st_size))
    for folder in sorted({m.dst.split("/", 1)[0] for m in pl.moves}):
        target = root / folder
        if target.exists() and not target.is_dir():
            pl.conflicts.append(f"{folder}: a file with this name is in the way")
        elif not target.exists():
            pl.folders.append(folder)
    return pl


# ---------------- journal ----------------

def _journal_dir(p: Project) -> Path:
    return config.cache_dir("journals", store.project_id(Path(p.root)))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def save_journal(p: Project, j: dict) -> None:
    """Both copies: Application Support (all runs) and the event folder (the latest run)."""
    j["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_journal_dir(p) / f"{j['id']}.json", j)
    _write_json(Path(p.root) / JOURNAL_DIR / "journal.json", j)


def journals(p: Project) -> list[dict]:
    """Every run for this event, newest first."""
    out = []
    d = _journal_dir(p)
    for f in d.glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    local = Path(p.root) / JOURNAL_DIR / "journal.json"
    if local.exists():
        try:
            j = json.loads(local.read_text())
            if all(x["id"] != j["id"] for x in out):
                out.append(j)
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return sorted(out, key=lambda j: j["id"], reverse=True)


def last_applied(p: Project) -> dict | None:
    return next((j for j in journals(p) if j["status"] in ("applied", "applying", "failed")), None)


# ---------------- apply / undo ----------------

def apply(p: Project, st: Structure, pl: Plan, preset: dict, progress: Progress | None = None,
          extras: Callable[[Project, Structure, dict], list[tuple[str, bytes]]] | None = None,
          force: bool = False) -> dict:
    """Move the files. `extras` returns generated files (index, contact sheets) to write afterwards."""
    check_allowed(p, force)
    if not pl.ok:
        raise RuntimeError("the plan has conflicts: " + "; ".join(pl.conflicts[:5]))
    root = Path(p.root)
    j = {"version": 1, "id": datetime.now().strftime("%Y%m%d-%H%M%S"), "project": p.name, "root": str(root),
         "created": datetime.now().isoformat(timespec="seconds"), "status": "applying",
         "moves": [asdict(m) for m in pl.moves], "dirs_created": [], "files_created": [], "files_replaced": []}
    save_journal(p, j)                                         # before anything moves

    try:
        for folder in pl.folders:
            (root / folder).mkdir()
            j["dirs_created"].append(folder)
        for i, m in enumerate(j["moves"]):
            src, dst = root / m["src"], root / m["dst"]
            if dst.exists():
                raise FileExistsError(f"{m['dst']} appeared during the run; stopped without overwriting")
            if src.stat().st_size != m["size"]:
                raise RuntimeError(f"{m['src']} changed size since the plan; stopped")
            os.rename(src, dst)
            m["status"] = "moved"
            if progress:
                progress("move", i + 1, len(j["moves"]))
            if (i + 1) % SAVE_EVERY == 0:
                save_journal(p, j)
    except Exception:
        j["status"] = "failed"
        save_journal(p, j)
        _sync_project(p, j)
        raise

    _sync_project(p, j)
    if extras:
        for rel, data in extras(p, st, preset):
            _write_generated(p, j, rel, data)
    j["status"] = "applied"
    save_journal(p, j)
    return j


def _write_generated(p: Project, j: dict, rel: str, data: bytes) -> None:
    """Index and contact sheets. Anything already at that path is set aside (and restored by undo)."""
    root = Path(p.root)
    target = root / rel
    for parent in reversed(Path(rel).parents[:-1]):
        if not (root / parent).exists():
            (root / parent).mkdir()
            j["dirs_created"].append(str(parent))
    if target.exists():
        keep = Path(JOURNAL_DIR) / "replaced" / j["id"] / rel
        (root / keep).parent.mkdir(parents=True, exist_ok=True)
        os.rename(target, root / keep)
        j["files_replaced"].append({"path": rel, "kept": str(keep)})
    target.write_bytes(data)
    j["files_created"].append(rel)


def _sync_project(p: Project, j: dict, undo: bool = False) -> None:
    """Point the project's clips (and sidecars) at where the files are now."""
    for m in j["moves"]:
        c = p.clips.get(m["clip"])
        if not c:
            continue
        done = m["status"] == ("undone" if undo else "moved")
        if not done:
            continue
        old, new = (m["dst"], m["src"]) if undo else (m["src"], m["dst"])
        if m["kind"] == "clip" and c.rel == old:
            c.rel = new
        elif m["kind"] == "sidecar":
            c.sidecars = [new if s == old else s for s in c.sidecars]
    p.save()


def undo(p: Project, journal: dict | None = None, progress: Progress | None = None) -> dict:
    """Move every file of the last run back to its exact original path and name."""
    j = journal or last_applied(p)
    if j is None:
        raise RuntimeError("nothing to undo")
    root = Path(p.root)
    j["status"] = "undoing"
    save_journal(p, j)
    problems = []
    moves = j["moves"]
    for i, m in enumerate(reversed(moves)):
        src, dst = root / m["src"], root / m["dst"]
        if dst.exists() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            os.rename(dst, src)
            m["status"] = "undone"
        elif src.exists() and dst.exists():
            problems.append(f"{m['src']} and {m['dst']} both exist; left as they are")
        elif src.exists():
            if m["status"] == "moved":
                m["status"] = "undone"                 # already back (an earlier undo)
        else:
            m["status"] = "missing"
            problems.append(f"{m['dst']} is missing")
        if progress:
            progress("undo", i + 1, len(moves))
    for rel in reversed(j.get("files_created", [])):
        f = root / rel
        if f.is_file():
            f.unlink()                                  # our own generated file, never footage
    for r in j.get("files_replaced", []):
        kept, orig = root / r["kept"], root / r["path"]
        if kept.exists() and not orig.exists():
            os.rename(kept, orig)
    for d in sorted(j.get("dirs_created", []), key=lambda s: s.count("/"), reverse=True):
        try:
            (root / d).rmdir()                          # only if empty
        except OSError:
            pass
    j["status"] = "undone" if not problems else "undone_with_problems"
    j["problems"] = problems
    save_journal(p, j)
    _sync_project(p, j, undo=True)
    return j


# ---------------- backup ----------------

def backup(p: Project, dest: Path, progress: Progress | None = None) -> dict:
    """Copy every clip and sidecar to dest/<event>/ and verify each copy by xxHash before any move."""
    root = Path(p.root)
    target = Path(dest).expanduser() / p.name.strip()
    if _inside(target, root) or _inside(root, target):
        raise ValueError("the backup must go outside the event folder")
    files = [rel for c in p.clips.values() for rel in [c.rel, *c.sidecars]]
    need = sum((root / r).stat().st_size for r in files)
    probe = target
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if need > free:
        raise OSError(f"not enough space on the backup drive: need {need / 1e9:.1f} GB, free {free / 1e9:.1f} GB")
    copied = verified = 0
    t0 = time.time()
    for i, rel in enumerate(files):
        src, dst = root / rel, target / rel
        h_src = checks.full_hash(src)
        if not (dst.exists() and dst.stat().st_size == src.stat().st_size and checks.full_hash(dst) == h_src):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            if checks.full_hash(dst) != h_src:
                raise OSError(f"backup copy of {rel} does not match the original")
        verified += 1
        if progress:
            progress("backup", i + 1, len(files))
    return {"dest": str(target), "files": len(files), "copied": copied, "verified": verified,
            "bytes": need, "seconds": round(time.time() - t0)}


def _inside(a: Path, b: Path) -> bool:
    try:
        a.resolve().relative_to(b.resolve())
        return True
    except ValueError:
        return False
