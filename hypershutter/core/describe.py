"""Pass 1: describe every clip from its contact sheets (Claude vision, one call per clip).

The model sees the sheets plus capture time, duration and camera. It never sees file names
or folder paths: in an organized project the folder name is the answer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable

from hypershutter.core import config, cost, credentials, sheets, store
from hypershutter.core.frames import Frame, FrameSettings
from hypershutter.core.media import Clip, fmt_duration
from hypershutter.core.project import Project

PROMPT_VERSION = "d3"
MAX_SHEETS = 20                      # per request; longer clips are subsampled evenly
FALLBACK_BETA = "server-side-fallback-2026-07-01"

MOMENTS = [
    "decor", "details", "church_exterior", "church_interior", "nature_place", "portraits_posed",
    "guests_arrival", "candid_family", "catechism", "sacrament", "anointing", "immersion", "dressing",
    "candles_circle", "communion", "ceremony_other", "wishes_congratulations", "treats_outside",
    "reception_venue", "reception_people", "food", "kids_activity", "musicians", "dancing",
    "getting_ready_groom", "getting_ready_bride", "rings", "crowns", "common_cup", "exit_rice",
    "couple_shoot", "first_dance", "speech_to_camera", "aerial", "unusable",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "English, 1-3 sentences: what happens, who, where"},
        "description_el": {"type": "string", "description": "Greek, one short sentence for the shot index"},
        "location": {"type": "string", "enum": ["church_exterior", "church_interior", "narthex_porch", "outdoors_near_church",
                                               "reception_venue", "garden_park", "house_indoors", "street_town", "studio",
                                               "aerial", "other"]},
        "moments": {"type": "array", "items": {"type": "string", "enum": MOMENTS}},
        "people": {"type": "array", "items": {"type": "string"}},
        "shot_type": {"type": "string", "enum": ["wide", "medium", "close_up", "detail", "aerial", "mixed"]},
        "take": {"type": "string", "enum": ["continuous_take", "cutaway", "mixed"]},
        "posed": {"type": "boolean", "description": "people pose for or look into the camera"},
        "priest_in_vestments_at_font": {"type": "boolean"},
        "notable": {"type": "array", "items": {"type": "object", "properties": {
            "t": {"type": "number"}, "what": {"type": "string"}}, "required": ["t", "what"], "additionalProperties": False}},
        "quality_issues": {"type": "array", "items": {"type": "string", "enum": [
            "blurry", "dark", "black", "floor_or_ground", "accidental", "shaky", "overexposed", "obstructed"]}},
        "usable": {"type": "boolean"},
        "star": {"type": "boolean", "description": "an emotional or beautiful shot an editor would want"},
        "confidence": {"type": "number"},
    },
    "required": ["description", "description_el", "location", "moments", "people", "shot_type", "take", "posed",
                 "priest_in_vestments_at_font", "notable", "quality_issues", "usable", "star", "confidence"],
    "additionalProperties": False,
}

SYSTEM = """You analyse one video clip from a professional videographer's footage of a Greek Orthodox \
event (baptism, wedding or similar). Your description will be used, together with all other clips of the \
same day, to sort the footage into the parts of the day the way the videographer does it.

You get the clip as contact sheets: frames in time order, left to right, top to bottom. Under each frame: \
the time inside the clip (m:ss) and the time of day. Density is about one frame every 1-2 seconds.

How to read the footage:
- The operator often presses record while walking: the first seconds may show the floor or a swing of the \
camera. Judge the clip by what most frames show; report floor/accidental only if the clip is mostly that.
- continuous_take = a long take that follows an ongoing action (a ceremony, a speech, a dance). cutaway = a \
short shot of a face, a detail or a reaction meant to be cut in. A long clip that wanders over many subjects is mixed.
- posed = people stand still and pose or look into the lens for a portrait. People talking to each other, \
greeting, playing or walking are candid (posed = false).
- Greek baptism day: decor, candy bar and the name sign; details (clothes, shoes, candle, oil cloths, oil \
bottles, cross); the empty church; family portraits; guests arriving. Catechism (κατήχηση): usually in the \
narthex or porch, the priest reads prayers over the baby held by the godparent, the godparent recites the \
Creed. Sacrament (μυστήριο): the priest in vestments at the font; oil blessing, undressing, anointing, \
immersion (βουτιά), chrism, dressing in white, candles circle, communion. Then treats outside the church \
(κέρασμα), wishes, reception, kids, musicians, dancing.
- Greek wedding day: getting ready (groom, bride), rings, crowns (στέφανα), common cup, «Ησαΐα χόρευε», exit \
with rice, couple photo shoot, reception, first dance, dancing.
- Mark priest_in_vestments_at_font only when that is visible.
- notable: up to 4 moments worth finding later, with the time inside the clip in seconds.
- people: short role words (priest, baby, mother, father, godparent, grandparents, guests, children, bride, \
groom, musicians, …). Never guess names.
- confidence: how sure you are about the moments and location (0 to 1).

Answer only with the JSON object."""


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    calls: int = 0
    refusals: int = 0
    seconds: float = 0.0          # summed request time
    wall: float = 0.0             # elapsed time of the whole pass
    by_model: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, u, model: str) -> None:
        with self.lock:
            self._add(u, model)

    def _add(self, u, model: str) -> None:
        self.input += u.input_tokens or 0
        self.output += u.output_tokens or 0
        self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.calls += 1
        m = self.by_model.setdefault(model, [0, 0])
        m[0] += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        m[1] += u.output_tokens or 0

    def cost(self) -> float:
        total = 0.0
        for model, (tin, tout) in self.by_model.items():
            pin, pout = cost.MODELS.get(model, cost.MODELS[cost.DEFAULT_MODEL])["price"]
            total += tin / 1e6 * pin + tout / 1e6 * pout
        return round(total, 3)


def camera_label(p: Project, clip: Clip) -> str:
    d = p.devices.get(clip.device)
    if d and d.kind == "drone":
        return "drone (aerial camera)"
    if d and d.kind == "camera":
        return "main camera" if d.id == "A" else f"second camera ({d.id})"
    return "camera"


def clip_text(p: Project, clip: Clip, event_type: str) -> str:
    start = p.corrected(clip)
    end = start + timedelta(seconds=clip.duration) if start else None
    pr = clip.probe
    lines = [
        f"Event type: {event_type}.",
        f"Recorded by: {camera_label(p, clip)}, {pr.get('width')}x{pr.get('height')} at {pr.get('fps')} fps, "
        f"{'with' if clip.has_audio else 'no'} audio.",
        f"Duration: {fmt_duration(clip.duration)} ({clip.duration:.1f} s).",
    ]
    if start:
        lines.append(f"Time of day: {start:%H:%M:%S}–{end:%H:%M:%S}.")
    return "\n".join(lines)


def _subsample(frames: list[Frame], max_frames: int) -> list[Frame]:
    if len(frames) <= max_frames:
        return frames
    step = len(frames) / max_frames
    return [frames[int(k * step)] for k in range(max_frames)]


def _cache_file(p: Project, clip: Clip, model: str, fs: FrameSettings) -> Path:
    """Keyed by the file itself (name, size, mtime), not by the project: a copy of the same clip
    or a re-mounted drive is not paid for twice. Older per-project caches are moved over."""
    key = store.file_key(clip.name, clip.size, clip.mtime)
    tag = hashlib.sha1(f"{key}|{model}|{fs.key()}|{PROMPT_VERSION}".encode()).hexdigest()[:24]
    path = config.cache_dir("describe") / f"{tag}.json"
    legacy = config.cache_dir("describe") / store.project_id(Path(p.root)) / f"{tag}.json"
    if not path.exists() and legacy.exists():
        legacy.rename(path)
    return path


def cached(p: Project, clip: Clip, model: str, fs: FrameSettings) -> dict | None:
    """A clip's description if pass 1 already ran with these settings (never calls the API)."""
    cf = _cache_file(p, clip, model, fs)
    return json.loads(cf.read_text()) if cf.exists() else None


def describe_clip(client, p: Project, clip: Clip, frames: list[Frame], fs: FrameSettings, model: str,
                  effort: str, event_type: str, usage: Usage) -> dict:
    cf = _cache_file(p, clip, model, fs)
    if cf.exists():
        return json.loads(cf.read_text())
    layout = sheets.SheetLayout()
    sub = _subsample(frames, MAX_SHEETS * layout.per_sheet)
    paths = sheets.clip_sheets(clip, sub, p.corrected(clip), fs, layout,
                               variant="" if len(sub) == len(frames) else f"_sub{len(sub)}")
    content = []
    for i, sp in enumerate(paths):
        content.append({"type": "text", "text": f"Sheet {i + 1} of {len(paths)}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(sp.read_bytes()).decode()}})
    content.append({"type": "text", "text": clip_text(p, clip, event_type) + "\n\nDescribe this clip."})
    t0 = time.time()
    resp = client.beta.messages.create(
        model=model, max_tokens=8000, betas=[FALLBACK_BETA], fallbacks="default",
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    usage.add(resp.usage, resp.model or model)
    usage.seconds += time.time() - t0
    if resp.stop_reason == "refusal":
        usage.refusals += 1
        out = {"refused": True, "category": getattr(resp.stop_details, "category", None)}
    else:
        text = next(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
    out["_model"] = resp.model or model
    cf.write_text(json.dumps(out, ensure_ascii=False))
    return out


def describe_all(p: Project, frames_by_clip: dict[str, list[Frame]], fs: FrameSettings, model: str = cost.DEFAULT_MODEL,
                 effort: str = "low", event_type: str = "baptism", workers: int = 8,
                 progress: Callable[[str, int, int], None] | None = None) -> tuple[dict[str, dict], Usage]:
    client = credentials.client()
    usage = Usage()
    ids = sorted(frames_by_clip, key=lambda c: (p.corrected(p.clips[c]) or 0, c))
    results: dict[str, dict] = {}
    done = 0

    def work(cid: str):
        return cid, describe_clip(client, p, p.clips[cid], frames_by_clip[cid], fs, model, effort, event_type, usage)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for cid, out in ex.map(work, ids):
            results[cid] = out
            done += 1
            if progress and (done % 10 == 0 or done == len(ids)):
                progress("describe", done, len(ids))
    return results, usage

