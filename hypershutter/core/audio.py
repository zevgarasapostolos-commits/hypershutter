"""Low-rate mono audio extraction with a disk cache (for sync, later for cut points)."""

from __future__ import annotations

import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from hypershutter.core import config, store
from hypershutter.core.media import Clip

SR = 4000


def _cache_path(clip: Clip, sr: int) -> Path:
    key = store.file_key(clip.name, clip.size, clip.mtime)
    return config.cache_dir("audio") / f"{hashlib.sha1(key.encode()).hexdigest()}_{sr}.npy"


def load(root: Path, clip: Clip, sr: int = SR) -> np.ndarray | None:
    cp = _cache_path(clip, sr)
    if cp.exists():
        return np.load(cp)
    ffmpeg = config.find_tool("ffmpeg") or "ffmpeg"
    r = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", str(root / clip.rel), "-map", "0:a:0", "-vn",
                        "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"], capture_output=True, timeout=1800)
    if r.returncode != 0 or not r.stdout:
        return None
    a = np.frombuffer(r.stdout, dtype=np.float32).copy()
    np.save(cp, a)
    return a


def load_many(root: Path, clips: list[Clip], sr: int = SR, workers: int = 4) -> dict[str, np.ndarray]:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        arrays = list(ex.map(lambda c: load(root, c, sr), clips))
    return {c.id: a for c, a in zip(clips, arrays) if a is not None and len(a)}
