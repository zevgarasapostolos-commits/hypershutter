"""Music for the highlights: beat grid of the song and the cut grid fitted to it.

The videographer's template is a list of cut times on his usual song (docs/workflow-editing.md
§7). For that song the template is used as is. For another song the template's rhythm (slot
lengths in beats) is replayed on the new song's beat grid, so cuts still land on beats.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from hypershutter.core import config

SR = 11025
HOP = 256
N_FFT = 1024
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".aif", ".aiff"}


@dataclass
class Grid:
    slots: list[float]                         # cut times in seconds; slot i runs slots[i] -> slots[i+1] (or end)
    end: float
    slow: dict[int, float] = field(default_factory=dict)   # slot index -> speed
    marks: dict[str, float] = field(default_factory=dict)  # title, film1, film2, intro_end, end_montage
    beat: float = 0.0

    def slot_len(self, i: int) -> float:
        return (self.slots[i + 1] if i + 1 < len(self.slots) else self.end) - self.slots[i]

    def index_at(self, t: float) -> int:
        return max(i for i, s in enumerate(self.slots) if s <= t + 1e-6)


def find_song(root: Path) -> Path | None:
    """The song in the event's music folder (the largest audio file), if there is one."""
    for name in ("music", "Music", "MUSIC", "μουσική"):
        d = root / name
        if d.is_dir():
            songs = [f for f in d.iterdir() if f.suffix.lower() in AUDIO_EXT and not f.name.startswith("._")]
            if songs:
                return max(songs, key=lambda f: f.stat().st_size)
    return None


def load(path: Path, sr: int = SR) -> np.ndarray:
    ff = config.find_tool("ffmpeg")
    raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_envelope(y: np.ndarray, hop: int = HOP, n_fft: int = N_FFT) -> np.ndarray:
    """Half-wave rectified spectral flux, normalised."""
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop] * np.hanning(n_fft)
    mag = np.log1p(np.abs(np.fft.rfft(frames, axis=1)))
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")         # remove the slow trend
    flux = np.maximum(flux, 0)
    return flux / (flux.max() or 1.0)


def beat_grid(env: np.ndarray, sr: int = SR, hop: int = HOP, bpm_range=(70, 180)) -> tuple[float, float]:
    """(beat period s, phase s) from the autocorrelation of the onset envelope and a phase search."""
    fps = sr / hop
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lo, hi = int(fps * 60 / bpm_range[1]), int(fps * 60 / bpm_range[0])
    # comb over multiples, so a 3/2 or 2x relative of the beat does not win
    score = [sum(ac[k * L] / k for k in range(1, 5) if k * L < len(ac)) for L in range(lo, hi + 1)]
    lag = lo + int(np.argmax(score))
    # refine below one frame: the period whose beat train lines up best over the whole song
    best = (-1.0, float(lag), 0.0)
    for per in np.arange(lag - 1.0, lag + 1.0, 0.02):
        for ph in range(int(per) + 1):
            idx = np.round(ph + np.arange(0, (len(env) - ph) / per) * per).astype(int)
            idx = idx[idx < len(env)]
            sc = float(env[idx].sum()) / max(1, len(idx))
            if sc > best[0]:
                best = (sc, per, float(ph))
    _, per, ph = best
    # a flux frame peaks when the onset enters its window: report the onset itself
    return float(per / fps), float(ph / fps + N_FFT / sr)


def analyse(path: Path) -> dict:
    y = load(path)
    env = onset_envelope(y)
    period, phase = beat_grid(env)
    return {"duration": len(y) / SR, "beat": period, "phase": phase}


def fit(template: dict, song: dict) -> Grid:
    """The template's cut grid on this song."""
    slots = [float(t) for t in template["slots"]]
    slow = {int(k): float(v) for k, v in template.get("slow", {}).items()}
    marks = {k: float(v) for k, v in template.get("marks", {}).items()}
    if abs(song["duration"] - template["song_duration"]) < 1.0:            # the template's own song
        return Grid(slots, float(template["end"]), slow, marks, song["beat"])
    ratio = song["beat"] / template["beat"]
    end_limit = song["duration"] - 1.0

    def snap(t: float) -> float:
        b = song["phase"] + round((t - song["phase"]) / (song["beat"] / 2)) * (song["beat"] / 2)
        return max(0.0, b)

    new = [0.0]
    for a, b in zip(slots, slots[1:] + [float(template["end"])]):
        nxt = snap(new[-1] + (b - a) * ratio)
        if nxt <= new[-1]:
            nxt = new[-1] + song["beat"] / 2
        if nxt >= end_limit:
            break
        new.append(nxt)
    end = new.pop() if len(new) > 1 else end_limit
    scale = end / float(template["end"])
    marks = {k: snap(v * scale) for k, v in marks.items()}
    return Grid(new, end, {i: s for i, s in slow.items() if i < len(new)}, marks, song["beat"])
