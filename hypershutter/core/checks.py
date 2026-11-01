"""Duplicate and corrupt-file checks. Flag only: nothing is ever deleted or modified."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import xxhash

from hypershutter.core.media import Clip

PARTIAL = 1 << 20      # 1 MiB from the start and from the end


def _partial_hash(path: Path, size: int) -> str:
    h = xxhash.xxh3_128()
    with open(path, "rb") as f:
        h.update(f.read(PARTIAL))
        if size > 2 * PARTIAL:
            f.seek(size - PARTIAL)
            h.update(f.read(PARTIAL))
    return h.hexdigest()


def _full_hash(path: Path) -> str:
    h = xxhash.xxh3_128()
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def find_corrupt(clips: list[Clip]) -> dict[str, str]:
    """clip id -> reason, for empty, unreadable or stream-less files."""
    bad: dict[str, str] = {}
    for c in clips:
        if c.size == 0:
            bad[c.id] = "zero-length file"
        elif "error" in c.probe:
            bad[c.id] = f"unreadable: {c.probe['error']}"
        elif c.duration <= 0:
            bad[c.id] = "no duration"
        elif c.kind == "video" and not c.probe.get("vcodec"):
            bad[c.id] = "no video stream"
        elif c.kind == "audio" and not c.probe.get("acodec"):
            bad[c.id] = "no audio stream"
    return bad


def find_duplicates(root: Path, clips: list[Clip]) -> list[list[str]]:
    """Groups of clip ids with identical content: size, then partial hash, then full hash."""
    by_size: dict[int, list[Clip]] = defaultdict(list)
    for c in clips:
        if c.size > 0:
            by_size[c.size].append(c)
    groups: list[list[str]] = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_partial: dict[str, list[Clip]] = defaultdict(list)
        for c in same_size:
            by_partial[_partial_hash(root / c.rel, c.size)].append(c)
        for cand in by_partial.values():
            if len(cand) < 2:
                continue
            by_full: dict[str, list[Clip]] = defaultdict(list)
            for c in cand:
                by_full[_full_hash(root / c.rel)].append(c)
            groups.extend(sorted(c.id for c in g) for g in by_full.values() if len(g) > 1)
    return groups


def run_checks(root: Path, clips: list[Clip]) -> dict:
    """Writes flags onto the clips and returns a summary."""
    corrupt = find_corrupt(clips)
    dups = find_duplicates(root, [c for c in clips if c.id not in corrupt])
    by_id = {c.id: c for c in clips}
    for cid, reason in corrupt.items():
        by_id[cid].flags.append(f"corrupt: {reason}")
    for g in dups:
        for cid in g[1:]:
            by_id[cid].flags.append(f"duplicate of {g[0]}")
    return {"corrupt": corrupt, "duplicates": dups}
