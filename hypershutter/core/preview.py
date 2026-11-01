"""Low-res preview of a sequence (960x540, 25 fps) for checking before opening Premiere.

Picture: the top enabled video item at every moment (V2 cutaways over V1), black where there is
none. Sound: every audio item at its place with its fades, mixed. Sources are read only.
"""

from __future__ import annotations

import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from hypershutter.core import config
from hypershutter.core.xmeml import FPS, Item, Sequence

W, H = 960, 540
MAX_AUDIO_INPUTS = 50          # items per ffmpeg call when laying out one track
SR_OUT = 48000


def picture(seq: Sequence) -> list[tuple[Item | None, int, int]]:
    """Flattened picture: (item or None for black, seq start, seq end), V2 over V1."""
    cuts = sorted({0, seq.duration} | {x for tr in seq.video for it in tr for x in (it.start, it.end)})
    out: list[tuple[Item | None, int, int]] = []
    for a, b in zip(cuts, cuts[1:]):
        top = None
        for tr in seq.video:                               # later tracks are on top
            for it in tr:
                if it.enabled and it.start <= a and it.end >= b:
                    top = it
        if out and out[-1][0] is top and out[-1][2] == a:
            out[-1] = (top, out[-1][1], b)
        else:
            out.append((top, a, b))
    return out


def _segment(ff: str, item: Item | None, a: int, b: int, out: Path) -> None:
    dur = (b - a) / FPS
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
          f"fps={FPS},format=yuv420p")
    if item is None:
        cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}", "-t", f"{dur:.3f}"]
    else:
        src_in = item.src_in + (a - item.start) / FPS * item.speed
        cmd = [ff, "-v", "error", "-y", "-ss", f"{src_in:.3f}", "-t", f"{dur * item.speed + 0.2:.3f}",
               "-i", item.media.path]
        vf = f"setpts=PTS/{item.speed}," + vf if abs(item.speed - 1) > 1e-6 else vf
    cmd += ["-an", "-vf", vf, "-frames:v", str(b - a), "-c:v", "libx264", "-preset", "veryfast", "-crf", "31",
            str(out)]
    subprocess.run(cmd, check=True)


def _item_filter(k: int, it: Item, skip: float = 0.0) -> str:
    ch = f"c{min(it.channel, max(1, it.media.audio_channels)) - 1}"
    dur = it.frames / FPS - skip
    f = f"[{k}:a]pan=mono|c0={ch},aresample={SR_OUT},atrim=0:{dur:.4f},asetpts=N/SR/TB"
    if it.fade_in and skip <= 0:
        f += f",afade=t=in:d={it.fade_in / FPS:.3f}"
    if it.fade_out:
        f += f",afade=t=out:st={max(0.0, dur - it.fade_out / FPS):.3f}:d={it.fade_out / FPS:.3f}"
    return f


def _track(ff: str, items: list[Item], total: float, out: Path, tmp: Path) -> None:
    """One audio track as a single stream from 0 to `total`: silence in the gaps, items in place.
    (amix with long adelays ends early, so each track is laid out by concatenation instead.)"""
    parts: list[Path] = []
    cursor = 0.0
    items = sorted(items, key=lambda i: i.start)
    for g in range(0, len(items), MAX_AUDIO_INPUTS):
        cmd = [ff, "-v", "error", "-y"]
        chains, labels = [], []
        for it in items[g:g + MAX_AUDIO_INPUTS]:
            start = it.start / FPS
            skip = max(0.0, cursor - start)                     # overlaps the previous item: drop its head
            if it.frames / FPS - skip <= 0.01:
                continue
            gap = start + skip - cursor
            if gap > 0.001:
                chains.append(f"anullsrc=r={SR_OUT}:cl=mono,atrim=0:{gap:.4f}[g{len(labels)}]")
                labels.append(f"[g{len(labels)}]")
            k = len([c for c in cmd if c == "-i"])
            cmd += ["-ss", f"{it.src_in + skip * it.speed:.3f}", "-t", f"{it.frames / FPS - skip + 0.1:.3f}",
                    "-i", it.media.path]
            chains.append(_item_filter(k, it, skip) + f"[a{len(labels)}]")
            labels.append(f"[a{len(labels)}]")
            cursor = start + it.frames / FPS
        if not labels:
            continue
        chains.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[t]")
        part = tmp / f"{out.stem}_{g:04d}.wav"
        cmd += ["-filter_complex", ";".join(chains), "-map", "[t]", "-c:a", "pcm_s16le", str(part)]
        subprocess.run(cmd, check=True)
        parts.append(part)
    lst = tmp / f"{out.stem}.txt"
    lst.write_text("".join(f"file '{p_}'\n" for p_ in parts))
    src = ["-f", "concat", "-safe", "0", "-i", str(lst)] if parts else ["-f", "lavfi", "-i", f"anullsrc=r={SR_OUT}:cl=mono"]
    subprocess.run([ff, "-v", "error", "-y", *src, "-af", f"apad=whole_dur={total:.4f},atrim=0:{total:.4f}",
                    "-c:a", "pcm_s16le", str(out)], check=True)


def _mix(ff: str, seq: Sequence, total: float, out: Path, tmp: Path) -> Path | None:
    tracks = []
    for n, tr in enumerate(seq.audio):
        items = [it for it in tr if it.enabled and it.media.audio_channels]
        if items:
            path = tmp / f"track{n}.wav"
            _track(ff, items, total, path, tmp)
            tracks.append(path)
    if not tracks:
        return None
    cmd = [ff, "-v", "error", "-y"]
    for t in tracks:
        cmd += ["-i", str(t)]
    graph = "".join(f"[{k}:a]" for k in range(len(tracks))) + f"amix=inputs={len(tracks)}:normalize=0:duration=longest[m]"
    subprocess.run(cmd + ["-filter_complex", graph, "-map", "[m]", "-c:a", "pcm_s16le", str(out)], check=True)
    return out


def render(seq: Sequence, out: Path, workers: int = 4, progress: Callable[[str, int, int], None] | None = None) -> Path:
    ff = config.find_tool("ffmpeg")
    segs = picture(seq)
    total = seq.duration / FPS
    with tempfile.TemporaryDirectory(dir=config.cache_dir("preview")) as tmp:
        tmp = Path(tmp)
        files = [tmp / f"v{i:05d}.mp4" for i in range(len(segs))]
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for _ in ex.map(lambda a: _segment(ff, *a), [(it, s, e, f) for (it, s, e), f in zip(segs, files)]):
                done += 1
                if progress and (done % 10 == 0 or done == len(segs)):
                    progress("preview", done, len(segs) + 1)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{f}'\n" for f in files))
        video = tmp / "video.mp4"
        subprocess.run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)],
                       check=True)
        mix = _mix(ff, seq, total, tmp / "mix.wav", tmp)
        cmd = [ff, "-v", "error", "-y", "-i", str(video)]
        if mix:
            cmd += ["-i", str(mix), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
        cmd += ["-c:v", "copy", "-shortest", "-movflags", "+faststart", str(out)]
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)
    if progress:
        progress("preview", len(segs) + 1, len(segs) + 1)
    return out
