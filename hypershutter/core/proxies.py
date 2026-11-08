"""Background proxies (thesis §6.2).

A proxy is made for every video clip as soon as its copy is verified, at background priority, one
clip at a time, with the preset from presets/proxy/ (ProRes Proxy 1080p by default, on the Apple
silicon ProRes engine when there is one). It is stored as

    <project>/Proxies/<the clip's folder>/<the clip's name>.mov

so Premiere's "Attach Proxies" finds it, and it moves with its clip when the files are organized.
Frame extraction and the sound analysis read the proxy when there is one (much faster than 4K).
"""

from __future__ import annotations

import json
import os
import threading
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

from hypershutter.core import config
from hypershutter.core.jobs import Job, JobQueue
from hypershutter.core.media import VIDEO_EXT
from hypershutter.core.scan import probe_file

PROXY_DIR = "Proxies"
DEFAULT = "prores_proxy"
SAMPLE = 16                          # clips read to estimate the proxies of a whole card
INGESTING = threading.Event()        # set while a card copies: proxies then yield the disk and the CPU


def presets() -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((config.PRESETS_DIR / "proxy").glob("*.yaml"))}


def proxy_path(project: Path, rel: str) -> Path:
    r = Path(rel)
    return Path(project) / PROXY_DIR / r.parent / f"{r.stem}.mov"


def proxy_for(project: Path, rel: str) -> Path | None:
    p = proxy_path(project, rel)
    return p if p.exists() and p.stat().st_size > 0 else None


def is_proxy(rel: str) -> bool:
    return Path(rel).parts[:1] == (PROXY_DIR,)


def makes_proxy(rel: str) -> bool:
    return Path(rel).suffix.lower() in VIDEO_EXT and not is_proxy(rel) and not Path(rel).name.upper().endswith(".LRF")


def _length(path: str) -> tuple[float, float]:
    """Seconds and frames per second of a clip; zeros when it cannot be read."""
    info = probe_file(Path(path))
    return float(info.get("duration") or 0.0), float(info.get("fps") or 0.0)


@lru_cache(maxsize=16)
def _sample_ratio(sample: tuple[tuple[str, int], ...], preset_name: str) -> float:
    preset = presets().get(preset_name)
    if not preset:
        return 0.0
    rate = preset.get("estimate", {})
    with ThreadPoolExecutor(max_workers=4) as ex:
        lengths = list(ex.map(_length, (path for path, _ in sample)))
    proxy = source = 0.0
    for (_, size), (seconds, fps) in zip(sample, lengths):
        if seconds > 0 and fps > 0:
            proxy += seconds * (rate.get("mbps") or rate.get("mbps_per_fps", 0.0) * fps) * 1e6 / 8
            source += size
    return proxy / source if proxy and source else float(preset.get("size_ratio", 0.42))


def size_ratio(files: list[tuple[Path, int]], preset_name: str) -> float:
    """Proxy size / source size for these video files. A proxy's size follows the clip's length and
    frame rate, not the size of the camera file, so a sample of the clips is read to find the
    ratio for this card. The result is remembered: the space check runs on every change in the form."""
    step = max(1, len(files) // SAMPLE)
    return _sample_ratio(tuple((str(p), size) for p, size in files[::step][:SAMPLE]), preset_name)


def _duration(src: Path) -> float:
    ffprobe = config.find_tool("ffprobe") or "ffprobe"
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return 0.0


def command(src: Path, out: Path, preset: dict, fallback: bool = False) -> list[str]:
    ffmpeg = config.find_tool("ffmpeg") or "ffmpeg"
    v = preset["video"]
    venc = v["fallback"] if fallback else v["encoder"]
    vargs = v.get("fallback_args", []) if fallback else v.get("args", [])
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?",
           "-map_metadata", "0", "-vf", f"scale='min({preset['width']},iw)':-2", "-c:v", venc, *vargs,
           *preset["audio"]["args"], "-progress", "pipe:1", "-nostats", str(out)]
    tp = "/usr/sbin/taskpolicy"
    if not os.path.exists(tp):
        return cmd
    # while a card copies: background QoS (throttled CPU and disk, never slows the ingest);
    # otherwise utility QoS, which still leaves the app responsive but runs several times faster
    return [tp, "-b"] + cmd if INGESTING.is_set() else [tp, "-c", "utility"] + cmd


def build(src: Path, out: Path, preset_name: str = DEFAULT, progress: Callable[[float], None] | None = None) -> int:
    """Encode one proxy; written to a hidden temp file first, never over an existing file."""
    preset = presets()[preset_name]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.hspart{out.suffix}")
    dur = _duration(src) or 1.0
    last = ""
    for fallback in (False, True):
        proc = subprocess.Popen(command(src, tmp, preset, fallback), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if line.startswith("out_time_us=") and progress:
                try:
                    progress(int(line.split("=", 1)[1]) / 1e6 / dur)
                except ValueError:
                    pass
        proc.wait()
        last = proc.stderr.read()[-400:]
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            break
    else:
        tmp.unlink(missing_ok=True)                 # our own partial output, never footage
        raise RuntimeError(f"proxy failed: {last.strip()}")
    if out.exists():
        out.rename(out.with_name(f".{out.name}.hs-old-{int(time.time())}"))
    tmp.rename(out)
    return out.stat().st_size


def runner(job: Job, progress: Callable[[float], None]) -> int:
    return build(Path(job.project) / job.rel, Path(job.out), job.preset, progress)


def queue(db_path: Path | None = None, workers: int = 1) -> JobQueue:
    return JobQueue({"proxy": runner}, workers=workers, db_path=db_path)


def enqueue(q: JobQueue, project: Path, rels: list[str], preset: str = DEFAULT) -> int:
    """Queue proxies for these clips (video only, not proxies themselves, not ones already made)."""
    n = 0
    for rel in rels:
        if not makes_proxy(rel):
            continue
        if proxy_for(project, rel):
            continue
        if q.add("proxy", str(project), rel, preset, str(proxy_path(project, rel))):
            n += 1
    return n
