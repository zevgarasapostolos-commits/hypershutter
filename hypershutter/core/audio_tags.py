"""Audio analysis for sorting: what can be heard in every clip, over time (thesis §6.5).

Two local models, nothing is uploaded:
- a sound-event tagger (CED-mini, AudioSet's 527 classes, ONNX through sherpa-onnx) on 5 s windows,
  reduced to a few groups that matter at an event: speech, chanting, singing, music, applause,
  crowd, bells, water, vehicles …, plus the room acoustics (small room, large hall, outdoors);
- Whisper (core/transcribe.py) on clips with speech or chanting, reduced to cue categories:
  liturgy, the ritual moments (crowning, rings, immersion …), wishes to the camera, toasts.

Only these categories reach the AI model, never raw speech: compact, explainable, and no names.
Results are cached per file in Application Support.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from hypershutter.core import config, store
from hypershutter.core.media import Clip, fmt_duration

REPO = "k2-fsa/sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
VERSION = "a1"
SR = 16000
WINDOW = 5.0                     # seconds per tagged window
PRESENT = 0.25                   # a group is heard in a window when its strongest class reaches this
SILENT_DB = -50.0

# AudioSet class indices grouped into what matters for sorting an event day
GROUPS: dict[str, list[int]] = {
    "speech": [0, 1, 2, 3, 4, 5, 15],
    "shouting": [8, 9, 10, 11, 13],
    "laughter": [16, 17, 18, 19, 20, 21],
    "crying": [22, 23, 24, 25],
    "chanting": [28, 30, 31, 255, 258, 259],
    "singing": [27, 32, 33, 34, 254],
    "music": list(range(137, 200)) + [208, 209, 210] + list(range(216, 254)) + [256, 257] + list(range(260, 283)),
    "applause": [63, 66, 67],
    "crowd": [68, 69, 70, 71],
    "bells": [200, 201, 205, 207],
    "water": [288, 292, 293, 294, 295, 444, 445, 446, 449, 450, 451, 452],
    "wind": [283, 284, 285],
    "vehicle": [300, 306, 307, 308, 309, 314, 316, 321, 326, 327, 343, 348, 349, 352, 353],
    "animals": list(range(72, 137)),
    "fireworks": [426, 432, 433, 436],
    "dishes": [364, 365, 442],
    "camera_clicks": [416, 417],
}
PLACES = {506: "small room", 507: "large hall", 508: "public space", 509: "outdoors (town)", 510: "outdoors (nature)"}

# what Whisper heard, as categories (accents and case removed before matching)
CUES: dict[str, str] = {
    "crowning": r"στεφεται|στεφανω ?σον|δοξη και τιμη",
    "rings": r"αρραβωνιζεται",
    "isaiah": r"ησαια χορευε",
    "common_cup": r"ποτηριον σωτηριου|κοινον ποτηριον|κοινο ποτηρι",
    "immersion": r"βαπτιζεται",
    "renunciation": r"αποτασσ|συντασσ|εμφυσησ",
    "creed": r"πιστευω εις ενα θεον",
    "gospel": r"σοφια ορθοι|αγιου ευαγγελιου|εκ του κατα",
    "wishes": r"να ζησετε|να ζησει|να ζησουν|να ειστε (παντα )?(καλα|ευτυχισμεν|αγαπημεν)|ευτυχισμεν|καλα στεφανα|"
              r"καλοριζικ|συγχαρητηρ|να (τον|την|το|τα) χαιρεστε|να σας ζησει|ευχομαι",
    "toast": r"γεια μας|στην υγεια|εβιβα",
    "directions": r"κοιταξτε|χαμογελ|πλησιαστε|ελατε (εδω|πιο κοντα)|σταθειτε|μια φωτογραφια",
}


@dataclass
class Window:
    t: float
    db: float
    groups: dict[str, float]
    place: str


# ---------------- the tagger ----------------

_local = threading.local()
_labels_lock = threading.Lock()


def _files() -> tuple[str, str]:
    from huggingface_hub import hf_hub_download
    with _labels_lock:
        return hf_hub_download(REPO, "model.onnx"), hf_hub_download(REPO, "class_labels_indices.csv")


def _tagger():
    """One tagger per thread (the ONNX session is not shared between threads)."""
    t = getattr(_local, "tagger", None)
    if t is None:
        import sherpa_onnx
        model, labels = _files()
        cfg = sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(ced=model, num_threads=1, provider="cpu"),
            labels=labels, top_k=527)
        t = _local.tagger = sherpa_onnx.AudioTagging(cfg)
    return t


def labels() -> list[str]:
    _, path = _files()
    return [r["display_name"] for r in csv.DictReader(open(path))]


def tag_window(samples: np.ndarray) -> np.ndarray:
    """Probabilities of the 527 AudioSet classes for one window of 16 kHz mono audio."""
    tagger = _tagger()
    s = tagger.create_stream()
    s.accept_waveform(sample_rate=SR, waveform=samples)
    probs = np.zeros(527, dtype=np.float32)
    for e in tagger.compute(s):
        probs[e.index] = e.prob
    return probs


def window_of(t: float, samples: np.ndarray, probs: np.ndarray) -> Window:
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if len(samples) else 0.0
    db = 20 * np.log10(rms + 1e-9)
    groups = {g: round(float(probs[idx].max()), 3) for g, idx in GROUPS.items()}
    groups = {g: v for g, v in groups.items() if v >= 0.1}
    pi = max(PLACES, key=lambda i: probs[i])
    place = PLACES[pi] if probs[pi] >= 0.15 else ""
    return Window(round(t, 2), round(float(db), 1), groups, place)


# ---------------- per clip ----------------

def _cache(clip: Clip) -> Path:
    key = store.file_key(clip.name, clip.size, clip.mtime) + "|" + VERSION + "|" + REPO
    return config.cache_dir("audio_tags") / (hashlib.sha1(key.encode()).hexdigest()[:24] + ".json")


def analyze(root: Path, clip: Clip, path: Path | None = None) -> dict:
    """Tagged windows of one clip: {"windows": [...]} or {"no_audio": true}. Cached; a file that
    is not on disk gives {"missing": true} and is not cached."""
    cf = _cache(clip)
    if cf.exists():
        return json.loads(cf.read_text())
    path = Path(path) if path else Path(root) / clip.rel
    if not path.exists():
        return {"missing": True}
    if not clip.has_audio:
        out: dict = {"no_audio": True}
    else:
        ff = config.find_tool("ffmpeg") or "ffmpeg"
        proc = subprocess.Popen([ff, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0", "-vn",
                                 "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        n = int(WINDOW * SR)
        windows, t = [], 0.0
        while True:
            buf = proc.stdout.read(n * 4)
            if not buf:
                break
            a = np.frombuffer(buf, dtype=np.float32)
            if len(a) >= SR or not windows:            # a last scrap under 1 s is dropped
                windows.append(window_of(t, a, tag_window(a)))
            t += len(a) / SR
        proc.wait()
        out = {"windows": [w.__dict__ for w in windows]} if windows else {"no_audio": True}
    out["version"] = VERSION
    cf.write_text(json.dumps(out, ensure_ascii=False))
    return out


def windows(tags: dict) -> list[Window]:
    return [Window(**w) for w in tags.get("windows", [])]


def shares(tags: dict) -> dict[str, float]:
    """Share of the clip's windows in which each group is heard."""
    ws = windows(tags)
    if not ws:
        return {}
    out = {g: sum(w.groups.get(g, 0) >= PRESENT for w in ws) / len(ws) for g in GROUPS}
    out["silence"] = sum(w.db < SILENT_DB for w in ws) / len(ws)
    return {g: round(v, 2) for g, v in out.items() if v > 0}


def place(tags: dict) -> str:
    ws = [w.place for w in windows(tags) if w.place]
    return max(set(ws), key=ws.count) if ws else ""


def wants_speech(tags: dict, clip: Clip) -> bool:
    """Worth running Whisper: speech or chanting in at least a fifth of the clip."""
    s = shares(tags)
    return clip.duration >= 3 and s.get("speech", 0) + s.get("chanting", 0) >= 0.2


def cues(segments) -> list[str]:
    """Cue categories in a transcript; «liturgy» when most of what is said is liturgical."""
    from hypershutter.core.transcribe import LITURGY, _norm
    texts = [_norm(s.text) for s in segments if s.text.strip()]
    if not texts:
        return []
    out = []
    if sum(bool(LITURGY.search(t)) for t in texts) / len(texts) >= 0.3 and len(texts) >= 2:
        out.append("liturgy")
    for name, rx in CUES.items():
        r = re.compile(rx)
        if any(r.search(t) for t in texts):
            out.append(name)
    return out


def speech_cues(root: Path, clip: Clip, tags: dict, event_type: str, path: Path | None = None) -> list[str]:
    if not wants_speech(tags, clip):
        return []
    from hypershutter.core import transcribe
    return cues(transcribe.transcribe(Path(path) if path else Path(root) / clip.rel, event_type))


def locate(root: Path, clips: list[Clip], elsewhere: list[Path] = ()) -> dict[str, Path]:
    """Where each clip's file is: in the event folder, or else a file with the same name and size in
    one of `elsewhere` (footage moved to another drive after it was sorted; read-only use)."""
    found: dict[str, Path] = {}
    index: dict[tuple[str, int], Path] = {}
    for d in elsewhere:
        for f in Path(d).iterdir():
            if not f.name.startswith("._") and f.is_file():
                index.setdefault((f.name, f.stat().st_size), f)
    from hypershutter.core import proxies
    for c in clips:
        here = Path(root) / c.rel
        px = proxies.proxy_for(root, c.rel)
        if px:                                       # same sound, much less to read
            found[c.id] = px
        elif here.exists():
            found[c.id] = here
        elif (c.name, c.size) in index:
            found[c.id] = index[(c.name, c.size)]
    return found


# ---------------- text for the model ----------------

def short_line(tags: dict, heard: list[str]) -> str:
    """One line for pass 2, e.g. «chanting 80%, speech 40%; large hall; heard: liturgy, crowning»."""
    if tags.get("missing"):
        return ""
    if tags.get("no_audio"):
        return "no sound"
    s = shares(tags)
    if s.get("silence", 0) >= 0.8:
        return "silent"
    top = sorted(((v, g) for g, v in s.items() if g != "silence" and v >= 0.15),
                 key=lambda x: (-x[0], x[1] == "speech", x[1]))[:5]      # on a tie, speech (heard everywhere) last
    text = ", ".join(f"{g} {round(v * 100)}%" for v, g in top) or "ambient only"
    if place(tags):
        text += f"; {place(tags)}"
    if heard:
        text += "; heard: " + ", ".join(heard)
    return text


def _top(w: Window) -> tuple[str, ...]:
    on = sorted(((v, g) for g, v in w.groups.items() if v >= PRESENT), reverse=True)[:3]
    if not on:
        return ("quiet",) if w.db < SILENT_DB else ("ambient",)
    return tuple(sorted(g for _, g in on))


def timeline_text(tags: dict, heard: list[str], max_runs: int = 10) -> str:
    """Runs of the same sound groups over the clip, for pass 1: «0:00–0:40 chanting + speech; …»."""
    if tags.get("missing"):
        return ""
    if tags.get("no_audio"):
        return "The clip has no sound track."
    ws = windows(tags)
    runs: list[list] = []
    for w in ws:
        k = _top(w)
        if runs and runs[-1][2] == k:
            runs[-1][1] = w.t + WINDOW
        else:
            runs.append([w.t, w.t + WINDOW, k])
    while len(runs) > max_runs:                      # merge the shortest run into its longer neighbour
        i = min(range(len(runs)), key=lambda j: runs[j][1] - runs[j][0])
        j = i - 1 if i == len(runs) - 1 or (i > 0 and runs[i - 1][1] - runs[i - 1][0] >= runs[i + 1][1] - runs[i + 1][0]) else i + 1
        a, b = sorted((i, j))
        runs[a] = [runs[a][0], runs[b][1], runs[j][2]]
        del runs[b]
    end = ws[-1].t + WINDOW if ws else 0
    parts = [f"{fmt_duration(a)}–{fmt_duration(min(b, end))} {' + '.join(k)}" for a, b, k in runs]
    text = "Sound over time (local sound classifier): " + "; ".join(parts) + "."
    if place(tags):
        text += f" Room acoustics: mostly {place(tags)}."
    if heard:
        text += " Speech recognition heard: " + ", ".join(heard) + "."
    return text


# ---------------- the whole event ----------------

def analyze_all(p, clips: list[Clip], event_type: str, workers: int = 4, speech: bool = True,
                progress: Callable[[str, int, int], None] | None = None,
                elsewhere: list[Path] = ()) -> dict[str, dict]:
    """{clip id: {"tags": ..., "heard": [...]}} for every clip (tags in parallel, Whisper after)."""
    root = Path(p.root)
    paths = locate(root, clips, elsewhere)
    out: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, tags in zip(clips, ex.map(lambda c: analyze(root, c, paths.get(c.id) or root / c.rel), clips)):
            out[c.id] = {"tags": tags, "heard": []}
            done += 1
            if progress and (done % 10 == 0 or done == len(clips)):
                progress("audio", done, len(clips))
    if speech:
        todo = [c for c in clips if c.id in paths and wants_speech(out[c.id]["tags"], c)]
        for k, c in enumerate(todo, start=1):
            try:
                out[c.id]["heard"] = speech_cues(root, c, out[c.id]["tags"], event_type, paths.get(c.id))
            except Exception as e:                   # Whisper missing or a broken track: tags still count
                out[c.id]["heard_error"] = str(e)[:200]
            if progress and (k % 5 == 0 or k == len(todo)):
                progress("speech", k, len(todo))
    return out
