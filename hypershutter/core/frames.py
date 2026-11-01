"""Dense frame extraction with scene-change extras, cached in Application Support.

Measured on a 4K50 Sony master (docs/m2-frames.md): seeking to the keyframe at each sample
time with `-skip_frame nokey`, six frames in parallel, is ~4x faster than one decode pass per
clip, because only the sampled keyframes get decoded (the cameras put a keyframe every
0.48-0.6 s). Scene changes are then found by comparing consecutive samples and adding the
midpoint frame wherever the picture changed a lot.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from hypershutter.core import config, store
from hypershutter.core.media import Clip


@dataclass(frozen=True)
class FrameSettings:
    interval: float = 2.0          # one frame every N seconds (1, 2 or 4 in Settings)
    width: int = 640               # stored frame width; sheets tile them smaller
    scene_threshold: float = 0.12  # mean abs difference of 64x36 grey thumbnails (0..1)
    workers: int = 6

    def key(self) -> str:
        return f"i{self.interval:g}_w{self.width}_s{self.scene_threshold:g}"


@dataclass
class Frame:
    t: float          # seconds into the clip
    path: str
    scene: bool = False   # added because the picture changed between two samples


def sample_times(duration: float, interval: float) -> list[float]:
    """Centred samples: a 5 s clip at 2 s gives 1.0, 3.0; a 1 s clip gives 0.5."""
    if duration <= 0:
        return []
    if duration <= interval:
        return [round(duration / 2, 2)]
    n = int(duration // interval)
    start = (duration - (n - 1) * interval) / 2
    return [round(start + k * interval, 2) for k in range(n)]


def frame_dir(clip: Clip, settings: FrameSettings) -> Path:
    key = store.file_key(clip.name, clip.size, clip.mtime)
    d = config.cache_dir("frames", hashlib.sha1(key.encode()).hexdigest()[:20], settings.key())
    return d


def source_path(root: Path, clip: Clip) -> Path:
    """DJI .LRF proxies decode much faster and show the same frames."""
    for s in clip.sidecars:
        if s.lower().endswith(".lrf"):
            return root / s
    return root / clip.rel


def extract_one(src: Path, t: float, out: Path, width: int) -> bool:
    ffmpeg = config.find_tool("ffmpeg") or "ffmpeg"
    for tt in (t, max(0.0, t - 1.0)):            # past the last keyframe nothing comes out
        r = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-skip_frame", "nokey", "-noaccurate_seek",
                            "-ss", f"{tt:.3f}", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(out)],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True
    return False


def _thumb(path: str) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("L").resize((64, 36), Image.BILINEAR), dtype=np.float32) / 255.0


def change(a: str, b: str) -> float:
    return float(np.mean(np.abs(_thumb(a) - _thumb(b))))


def _name(t: float) -> str:
    return f"t{int(round(t * 1000)):09d}.jpg"


def load_cached(clip: Clip, settings: FrameSettings) -> list[Frame] | None:
    meta = frame_dir(clip, settings) / "frames.json"
    if not meta.exists():
        return None
    frames = [Frame(**f) for f in json.loads(meta.read_text())["frames"]]
    return frames if all(os.path.exists(f.path) for f in frames) else None


def extract_all(root: Path, clips: list[Clip], settings: FrameSettings = FrameSettings(),
                progress: Callable[[str, int, int], None] | None = None) -> dict[str, list[Frame]]:
    """Frames for every readable video clip. Already-cached clips are not touched again."""
    result: dict[str, list[Frame]] = {}
    todo = []
    for c in clips:
        if c.kind != "video" or any(f.startswith("corrupt") for f in c.flags) or c.duration <= 0:
            continue
        cached = load_cached(c, settings)
        if cached is not None:
            result[c.id] = cached
        else:
            todo.append(c)

    def run(jobs: list[tuple[Clip, float]], stage: str) -> dict[tuple[str, float], bool]:
        done, ok = 0, {}
        def work(job):
            c, t = job
            out = frame_dir(c, settings) / _name(t)
            return job, (out.exists() and out.stat().st_size > 0) or extract_one(source_path(root, c), t, out, settings.width)
        with ThreadPoolExecutor(max_workers=settings.workers) as ex:
            for (c, t), good in ex.map(work, jobs):
                ok[(c.id, t)] = good
                done += 1
                if progress and (done % 50 == 0 or done == len(jobs)):
                    progress(stage, done, len(jobs))
        return ok

    base_jobs = [(c, t) for c in todo for t in sample_times(c.duration, settings.interval)]
    ok = run(base_jobs, "frames")

    extra_jobs = []
    base: dict[str, list[Frame]] = {}
    for c in todo:
        d = frame_dir(c, settings)
        fs = [Frame(t, str(d / _name(t))) for t in sample_times(c.duration, settings.interval) if ok.get((c.id, t))]
        base[c.id] = fs
        for a, b in zip(fs, fs[1:]):
            if b.t - a.t >= 1.0 and change(a.path, b.path) > settings.scene_threshold:
                extra_jobs.append((c, round((a.t + b.t) / 2, 2)))
    ok_extra = run(extra_jobs, "scene frames") if extra_jobs else {}

    for c in todo:
        d = frame_dir(c, settings)
        extras = [Frame(t, str(d / _name(t)), scene=True) for (cid, t), good in ok_extra.items() if cid == c.id and good]
        frames = sorted(base[c.id] + extras, key=lambda f: f.t)
        (d / "frames.json").write_text(json.dumps({"clip": c.id, "settings": asdict(settings),
                                                   "frames": [asdict(f) for f in frames]}))
        result[c.id] = frames
    return result
