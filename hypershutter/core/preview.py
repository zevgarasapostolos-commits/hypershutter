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
MAX_AUDIO_INPUTS = 60          # per mix pass; longer sequences are mixed in chunks


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
    cmd += ["-an", "-vf", vf, "-frames:v", str(b - a), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            str(out)]
    subprocess.run(cmd, check=True)


def _mix(ff: str, items: list[Item], total: float, out: Path, base: Path | None = None) -> None:
    cmd = [ff, "-v", "error", "-y"]
    filters, labels = [], []
    if base is not None:
        cmd += ["-i", str(base)]
        labels.append("[0:a]")
    for k, it in enumerate(items, start=len(labels)):
        cmd += ["-ss", f"{it.src_in:.3f}", "-t", f"{it.frames / FPS:.3f}", "-i", it.media.path]
        ch = f"c{min(it.channel, max(1, it.media.audio_channels)) - 1}"
        f = f"[{k}:a]pan=mono|c0={ch},aresample=48000"
        if it.fade_in:
            f += f",afade=t=in:d={it.fade_in / FPS:.3f}"
        if it.fade_out:
            f += f",afade=t=out:st={max(0.0, (it.frames - it.fade_out) / FPS):.3f}:d={it.fade_out / FPS:.3f}"
        f += f",adelay={int(it.start / FPS * 1000)}|{int(it.start / FPS * 1000)}[s{k}]"
        filters.append(f)
        labels.append(f"[s{k}]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
                   f"atrim=0:{total:.3f}[m]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[m]", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True)


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
        audio_items = [it for tr in seq.audio for it in tr if it.enabled and it.media.audio_channels]
        mix = None
        for k in range(0, len(audio_items), MAX_AUDIO_INPUTS):
            nxt = tmp / f"mix{k}.wav"
            _mix(ff, audio_items[k:k + MAX_AUDIO_INPUTS], total, nxt, mix)
            mix = nxt
        cmd = [ff, "-v", "error", "-y", "-i", str(video)]
        if mix:
            cmd += ["-i", str(mix), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
        cmd += ["-c:v", "copy", "-shortest", "-movflags", "+faststart", str(out)]
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)
    if progress:
        progress("preview", len(segs) + 1, len(segs) + 1)
    return out
