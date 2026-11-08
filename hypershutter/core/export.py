"""Batch export with presets (thesis §6.10): per-clip transcodes of chosen clips, whole categories
or the whole event. No cutting, no editing: one output file per clip, same length.

Presets are editable YAML files in presets/export/ (codec, size, bitrate, audio, an optional .cube
LUT, the naming pattern). The output mirrors the category structure:

    <destination>/<preset>/<category folder>/<name>.<ext>

The jobs go to the same background queue as proxies (pause / resume, survives a restart). Space
is checked first; an existing file is never overwritten (the new one gets « (2)»).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from hypershutter.core import config, drives
from hypershutter.core.jobs import Job, JobQueue
from hypershutter.core.project import Project
from hypershutter.core.structure import Structure

EXPORT_DIR = "Exports"


def presets() -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((config.PRESETS_DIR / "export").glob("*.yaml"))}


@dataclass
class Item:
    clip: str
    src: str               # relative to the event folder
    out: Path
    seconds: float


def _free_name(path: Path, taken: set[str]) -> Path:
    k = 1
    out = path
    while out.exists() or str(out) in taken:
        k += 1
        out = path.with_name(f"{path.stem} ({k}){path.suffix}")
    taken.add(str(out))
    return out


def plan(p: Project, st: Structure | None, preset_name: str, dest: Path | None = None,
         clips: list[str] | None = None, folders: list[str] | None = None) -> list[Item]:
    """What would be written. `folders` are category keys or folder numbers ("05", "08a");
    nothing chosen = the whole event. Without a structure the current folders are mirrored."""
    preset = presets()[preset_name]
    dest = Path(dest) if dest else Path(p.root) / EXPORT_DIR
    base = dest / preset_name
    folder_of: dict[str, str] = {}
    number_of: dict[str, str] = {}
    if st is not None:
        for c in st.categories:
            for cid in c.clips:
                folder_of[cid] = c.folder
                number_of[cid] = f"{c.number:02d}{c.sub}"
    wanted = set(clips or [])
    if folders:
        keys = set(folders)
        for c in (st.categories if st else []):
            if c.key in keys or f"{c.number:02d}{c.sub}" in keys or c.folder in keys:
                wanted |= set(c.clips)
        if st is None:                               # not analysed here: the folders as they are on disk
            for c in p.clips.values():
                top = c.rel.split("/", 1)[0]
                if top in keys or top.split(" ", 1)[0] in keys:
                    wanted.add(c.id)
        if not wanted:
            return []
    chosen = [c for c in p.clips.values() if c.kind == "video" and (not wanted or c.id in wanted)]
    chosen.sort(key=lambda c: (folder_of.get(c.id, str(Path(c.rel).parent)), p.corrected(c) or 0, c.id))
    items, taken, counter = [], set(), {}
    for c in chosen:
        folder = folder_of.get(c.id) or str(Path(c.rel).parent)
        counter[folder] = counter.get(folder, 0) + 1
        stem = preset.get("naming", "{name}").format(name=Path(c.name).stem, folder=number_of.get(c.id, ""),
                                                     n=counter[folder])
        out = _free_name(base / folder / f"{stem}.{preset['extension']}", taken)
        items.append(Item(c.id, c.rel, out, c.duration))
    return items


def estimate_bytes(items: list[Item], preset_name: str) -> int:
    return int(sum(i.seconds for i in items) * presets()[preset_name].get("mbps", 20) * 1e6 / 8)


def check(items: list[Item], preset_name: str) -> list[str]:
    if not items:
        return ["nothing to export"]
    problem = drives.check_space(items[0].out.parent, estimate_bytes(items, preset_name))
    return [problem] if problem else []


def space(items: list[Item], preset_name: str) -> dict | None:
    """The space check as data, for the app's own language."""
    return drives.space_problem(items[0].out.parent, estimate_bytes(items, preset_name)) if items else None


def command(src: Path, out: Path, preset: dict, fallback: bool = False) -> list[str]:
    ffmpeg = config.find_tool("ffmpeg") or "ffmpeg"
    v = preset["video"]
    filters = []
    if preset.get("lut"):
        filters.append(f"lut3d=file='{Path(preset['lut']).expanduser()}'")
    if preset.get("width"):
        filters.append(f"scale='min({preset['width']},iw)':-2")
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0"]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", v["fallback"] if fallback else v["encoder"], *(v.get("fallback_args", []) if fallback else v.get("args", [])),
            *preset["audio"]["args"], "-progress", "pipe:1", "-nostats", str(out)]
    return cmd


def build(src: Path, out: Path, preset_name: str, seconds: float = 0.0,
          progress: Callable[[float], None] | None = None) -> int:
    preset = presets()[preset_name]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.hspart{out.suffix}")
    last = ""
    for fallback in (False, True):
        proc = subprocess.Popen(command(src, tmp, preset, fallback), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if line.startswith("out_time_us=") and progress and seconds:
                try:
                    progress(int(line.split("=", 1)[1]) / 1e6 / seconds)
                except ValueError:
                    pass
        proc.wait()
        last = proc.stderr.read()[-400:]
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            break
    else:
        tmp.unlink(missing_ok=True)                 # our own partial output, never footage
        raise RuntimeError(f"export failed: {last.strip()}")
    final = out if not out.exists() else _free_name(out, set())
    tmp.rename(final)
    return final.stat().st_size


def runner(job: Job, progress: Callable[[float], None]) -> int:
    meta = json.loads(job.meta) if job.meta else {}
    return build(Path(job.project) / job.rel, Path(job.out), job.preset, meta.get("seconds", 0.0), progress)


def queue(db_path: Path | None = None, workers: int = 1) -> JobQueue:
    return JobQueue({"export": runner}, workers=workers, db_path=db_path)


def enqueue(q: JobQueue, p: Project, items: list[Item], preset_name: str) -> int:
    n = 0
    for it in items:
        if q.add("export", str(p.root), it.src, preset_name, str(it.out), json.dumps({"seconds": it.seconds})):
            n += 1
    return n
