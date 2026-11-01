"""Per-device clock correction from shared audio (normalized cross-correlation), anchored on
the most trusted clock.

Short clips of one device ("needles") are searched inside the audio of another device
("haystack", concatenated in blocks). Every needle votes for a relative clock offset;
agreeing votes with a strong correlation peak decide it. This finds offsets of any size
(the main camera is usually ~14 h off) without a prior guess.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft

from hypershutter.core import audio
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project

# DJI drones take GPS time. DJI Mic recorders keep their own clock and have been 20–46 min off,
# so their file-name time ranks below a camera's.
TRUST = {"dji_name": 3.0, "dji_srt": 3.0, "sony_xml": 2.5, "creation_time": 1.5, "rec_name": 1.0, "mtime": 0.0}
SR = audio.SR
NEEDLE_MAX = 30.0            # s of each needle actually correlated
NEEDLE_MIN = 2.5
MAX_NEEDLES = 16
SEGMENT_EVERY = 300.0        # s between needle segments taken from one long recording
BLOCK = 600.0                # s of haystack per FFT
GAP = 2.0                    # s of silence between concatenated haystack clips
PSR_MIN = 9.0                # peak-to-sidelobe ratio for a usable vote (false peaks reached ~12)
PSR_STRONG = 25.0            # a single vote this strong is enough
AGREE = 2.0                  # s: votes within this distance agree (creation_time has 1 s resolution)


@dataclass
class Match:
    needle: str
    hay: str
    at: float      # seconds into the hay clip where the needle segment starts
    psr: float
    rel: float     # drift(needle device) - drift(hay device), seconds


def ncc(needle: np.ndarray, hay: np.ndarray, sr: int = SR) -> tuple[int, float]:
    """Normalized cross-correlation: best lag (samples, needle[0] -> hay[lag]) and its
    peak-to-sidelobe ratio. Beat GCC-PHAT on real church audio from two cameras
    (docs/m1-clock-sync.md): whitening amplifies reverb and hiss that differ per camera.
    """
    n, m = len(needle), len(hay)
    nfft = next_fast_len(n + m)
    cc = irfft(rfft(hay, nfft) * np.conj(rfft(needle, nfft)), nfft)
    lags = np.arange(-(n // 2), m - n // 2)      # allow half the needle to hang over an edge
    energy = np.concatenate([[0.0], np.cumsum(hay.astype(np.float64) ** 2)])
    win = energy[np.clip(lags + n, 0, m)] - energy[np.clip(lags, 0, m)]
    vals = cc[lags % nfft] / (np.sqrt(np.maximum(win, 1e-12)) * np.sqrt(float((needle ** 2).sum())) + 1e-12)
    vals[win < 0.1 * n * float(np.mean(hay ** 2))] = 0.0      # silence and the gaps between clips
    i = int(np.argmax(vals))
    excl = int(0.1 * sr)
    rest = np.concatenate([vals[: max(0, i - excl)], vals[i + excl:]])
    psr = float((vals[i] - rest.mean()) / (rest.std() + 1e-12)) if len(rest) > 10 else 0.0
    return int(lags[i]), psr


def _blocks(hay: list[Clip], arrays: dict[str, np.ndarray]):
    """Concatenate haystack clips (time order) into ~BLOCK-second arrays with an index."""
    out, cur, index, pos = [], [], [], 0
    gap = np.zeros(int(GAP * SR), np.float32)
    for c in hay:
        a = arrays.get(c.id)
        if a is None:
            continue
        if pos and pos + len(a) > BLOCK * SR:
            out.append((np.concatenate(cur), index)); cur, index, pos = [], [], 0
        index.append((pos, c.id, len(a)))
        cur += [a - a.mean(), gap]
        pos += len(a) + len(gap)
    if cur:
        out.append((np.concatenate(cur), index))
    return out


def _needles(clips: list[Clip]) -> list[tuple[Clip, float, float]]:
    """(clip, segment start, segment length), longest first and spread over the day.

    Long recordings (e.g. a lapel recorder) give one segment every SEGMENT_EVERY seconds,
    because only some of their stretches overlap the other device.
    """
    segs = []
    for c in clips:
        if c.duration < NEEDLE_MIN or not c.nominal:
            continue
        if c.duration <= 2 * NEEDLE_MAX:
            seg = min(c.duration, NEEDLE_MAX)
            segs.append((c, (c.duration - seg) / 2, seg))
        else:
            n = max(1, int(c.duration // SEGMENT_EVERY))
            step = (c.duration - NEEDLE_MAX) / n
            segs += [(c, step * (k + 0.5), NEEDLE_MAX) for k in range(n)]
    segs.sort(key=lambda s: -s[2])
    # First pass: at most 3 per half hour so one busy moment does not take every slot.
    out, rest, per_slot = [], [], {}
    for s in segs:
        slot = int((s[0].nominal_dt().timestamp() + s[1]) // 1800)
        (out if per_slot.get(slot, 0) < 3 else rest).append(s)
        per_slot[slot] = per_slot.get(slot, 0) + 1
    return (out + rest)[:MAX_NEEDLES]


def _match(root: Path, needle_clips: list[Clip], hay_clips: list[Clip]) -> list[Match]:
    needles = _needles(needle_clips)
    arrays = audio.load_many(root, [n[0] for n in needles] + hay_clips)
    hay_by_id = {c.id: c for c in hay_clips}
    blocks = _blocks(sorted(hay_clips, key=lambda c: c.nominal or ""), arrays)
    matches = []
    for clip, start, seg in needles:
        a = arrays.get(clip.id)
        if a is None:
            continue
        x = a[int(start * SR): int((start + seg) * SR)]
        if len(x) < NEEDLE_MIN * SR or float(np.sqrt(np.mean(x ** 2))) < 1e-4:
            continue
        x = x - x.mean()
        best = None
        for block, index in blocks:
            lag, psr = ncc(x, block)
            centre = lag + len(x) // 2
            for pos, cid, length in index:
                if pos <= centre < pos + length:
                    if best is None or psr > best[2]:
                        best = (cid, (lag - pos) / SR, psr)
                    break
        if best is None:
            continue
        hid, at, psr = best
        hay = hay_by_id[hid]
        rel = (hay.nominal_dt() + timedelta(seconds=at) - clip.nominal_dt() - timedelta(seconds=start)).total_seconds()
        # `at` = where the whole needle clip starts inside the hay clip (not just its segment).
        matches.append(Match(clip.id, hid, round(at - start, 2), round(psr, 1), round(rel, 2)))
    return matches


def vote(matches: list[Match]) -> tuple[float, float, list[Match]] | None:
    """(relative offset, confidence 0..1, agreeing matches) or None when not decisive."""
    good = [m for m in matches if m.psr >= PSR_MIN]
    if not good:
        return None
    clusters = [[x for x in good if abs(x.rel - m.rel) <= AGREE] for m in good]
    best = max(clusters, key=lambda cl: sum(x.psr for x in cl))
    if len(best) < 2 and best[0].psr < PSR_STRONG:
        return None
    rel = median(x.rel for x in best)
    support = sum(x.psr for x in best) / sum(x.psr for x in good)
    confidence = round(min(1.0, support * min(1.0, len(best) / 3 + 0.34)), 2)
    return rel, confidence, sorted(best, key=lambda m: -m.psr)


def _audio_clips(p: Project, dev: str) -> list[Clip]:
    return [c for c in p.device_clips(dev) if c.has_audio and c.nominal and not c.flags]


def relative_offset(p: Project, root: Path, a: str, b: str) -> tuple[float, float, list[Match]] | None:
    """drift(a) - drift(b) from shared audio; needles come from the device with less audio."""
    ca, cb = _audio_clips(p, a), _audio_clips(p, b)
    if not ca or not cb:
        return None
    flip = sum(c.duration for c in ca) > sum(c.duration for c in cb)
    needles, hay = (cb, ca) if flip else (ca, cb)
    sign = -1.0 if flip else 1.0
    staged = [h for h in hay if 20 <= h.duration <= 900]          # masters first: cheaper, usually enough
    for stage in ([staged, hay] if staged and len(staged) < len(hay) else [hay]):
        res = vote(_match(root, needles, stage))
        if res:
            rel, conf, ms = res
            return sign * rel, conf, ms
    return None


def _span(clips: list[Clip]) -> tuple[datetime, datetime] | None:
    ts = [(c.nominal_dt(), c.nominal_dt() + timedelta(seconds=c.duration)) for c in clips if c.nominal]
    return (min(t[0] for t in ts), max(t[1] for t in ts)) if ts else None


def choose_anchor(p: Project) -> str | None:
    """Most trusted audio device whose times are plausible next to the drone (GPS clock).

    Without a drone, a device whose median clip falls between 09:00 and midnight is plausible;
    a main camera that is ~14 h off lands in the early morning.
    """
    drone = _span(p.device_clips("DJI")) if "DJI" in p.devices else None
    best, best_score = None, -1.0
    for d in p.devices.values():
        clips = _audio_clips(p, d.id)
        if not clips:
            continue
        if drone:
            lo, hi = drone[0] - timedelta(hours=2), drone[1] + timedelta(hours=2)
            plaus = sum(lo <= c.nominal_dt() <= hi for c in clips) / len(clips)
        else:
            mid = sorted(c.nominal_dt() for c in clips)[len(clips) // 2]
            plaus = 1.0 if 9 <= mid.hour else 0.3
        score = TRUST.get(d.source, 0.0) + 2.0 * plaus + min(len(clips), 50) / 1000
        if score > best_score:
            best, best_score = d.id, score
    return best


def auto_sync(p: Project, root: Path, log: Callable[[str], None] = print) -> dict:
    """Sets drift on every device it can; returns a report. Manual offsets are kept."""
    for d in p.devices.values():
        if d.drift_status not in ("manual",):
            d.drift, d.drift_status, d.confidence, d.evidence = 0.0, "default", 0.0, []
    anchor = choose_anchor(p)
    report = {"anchor": anchor, "pairs": []}
    if anchor is None:
        log("no device with audio: clock offsets cannot be measured, defaults kept")
        return report
    p.devices[anchor].drift_status = "anchor" if p.devices[anchor].drift_status != "manual" else "manual"
    p.devices[anchor].confidence = 1.0
    synced = [anchor]
    pending = [d.id for d in p.devices.values() if d.id != anchor and _audio_clips(p, d.id)]
    progress = True
    while pending and progress:
        progress = False
        for dev in list(pending):
            for ref in synced:
                log(f"matching audio {dev} against {ref} …")
                res = relative_offset(p, root, dev, ref)
                report["pairs"].append({"device": dev, "ref": ref, "ok": bool(res)})
                if not res:
                    continue
                rel, conf, ms = res
                d = p.devices[dev]
                if d.drift_status != "manual":
                    # Whole seconds: every clock source we read has 1 s resolution.
                    d.drift = float(round(p.devices[ref].drift + rel))
                    d.drift_status, d.confidence = "auto", conf
                d.evidence = [asdict(m) | {"ref": ref} for m in ms[:6]]
                synced.append(dev); pending.remove(dev); progress = True
                break
    for dev in pending:
        if p.devices[dev].drift_status != "manual":
            p.devices[dev].drift_status = "unresolved"
    p.synced_at = datetime.now().isoformat(timespec="seconds")
    return report


def parse_offset(text: str) -> float:
    """'+14:00', '-0:44', '+03:00:44', '+50400' -> seconds."""
    t = text.strip()
    sign = -1.0 if t.startswith("-") else 1.0
    t = t.lstrip("+-")
    if ":" not in t:
        return sign * float(t)
    parts = [float(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.append(0.0)
    return sign * (parts[0] * 3600 + parts[1] * 60 + parts[2])


def set_manual(p: Project, dev_id: str, raw_offset: float) -> Device:
    """User override, expressed like the index: offset vs the raw clock reading."""
    d = p.devices[dev_id]
    d.drift = raw_offset - d.tz_offset
    d.drift_status, d.confidence = "manual", 1.0
    return d
