"""Pass 2: build this event's own category structure and assign every clip.

One text-only call over all clip descriptions on the corrected timeline, then deterministic
validation: every clip exactly once, ΡΟΗ/B-ROLL rule, drone folder, conservative smoothing of
isolated outliers, chronological numbering and Greeklish folder names. Without an API key or
internet the offline fallback segments the timeline by time gaps.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from hypershutter.core import config, cost, credentials
from hypershutter.core.greeklish import folder_name
from hypershutter.core.media import Clip, fmt_duration
from hypershutter.core.project import Project

FLOW, BROLL, NORMAL, DRONE, UNUSABLE = "ceremony_flow", "ceremony_broll", "normal", "drone", "unusable"
PROMPT_VERSION = "s4"
REVIEW_BELOW = 0.6
FLOW_MIN_S = 45.0                    # a ΡΟΗ master is a long main-camera take
BROLL_MAX_IN_FLOW_S = 30.0
NOTHING_SHOWN = {"floor_or_ground", "overexposed", "dark"}   # with nobody in frame: no picture of the event
SIGNALS = ("time", "camera", "image", "audio")    # what pass 2 may see about each clip (ablation study)
ALL_SIGNALS = frozenset(SIGNALS)

SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "label_el": {"type": "string", "description": "Greek, upper case, what this part of the day contains"},
            "description_el": {"type": "string", "description": "one Greek sentence for the shot index"},
            "kind": {"type": "string", "enum": [NORMAL, FLOW, BROLL, DRONE, UNUSABLE]},
            "ceremony": {"type": "string", "description": "for ceremony_flow / ceremony_broll: the shared Greek name, e.g. ΚΑΤΗΧΗΣΗ; else empty"},
        }, "required": ["id", "label_el", "description_el", "kind", "ceremony"], "additionalProperties": False}},
        "assignments": {"type": "array", "items": {"type": "object", "properties": {
            "clip": {"type": "integer"}, "part": {"type": "string"}, "confidence": {"type": "number"},
        }, "required": ["clip", "part", "confidence"], "additionalProperties": False}},
        "notes": {"type": "string"},
    },
    "required": ["parts", "assignments", "notes"],
    "additionalProperties": False,
}

SYSTEM = """You organize the footage of one Greek event day for a professional videographer, exactly the \
way he sorts it himself: one folder per part of the day, in chronological order, named after what is in it.

There is no fixed list of categories: every event gets its own structure built from what is actually in \
the footage. The preset below lists typical parts and their cues only as hints; skip parts that are not \
there, add parts that are (e.g. kids' face painting, musicians, a parents' photo shoot), split or merge as \
the footage requires. Prefer the videographer's level of granularity: typically 12-18 parts for a \
baptism, each a meaningful chunk of the day, not one part per clip.

Rules that always apply:
- Decide the time boundaries of the parts first from the timeline, then assign clip by clip: categories \
interleave in time (decor shot between portraits stays decor).
- Everything filmed inside the time window of a ceremony (catechism, sacrament, wedding service) belongs to \
that ceremony; things filmed before it belong to arrival, portraits, decor, etc.
- Start a new part when a new activity starts (a ceremony, treats, a photo shoot, face painting, live music, \
dancing) or the place changes. Do not split one continuous stretch at the same place by subject (e.g. \
posed shots after the ceremony stay one part, whoever is in them), unless the preset keeps those subjects \
apart for this kind of event: before a baptism decor, details, interior, exterior, portraits and arrival; at a \
wedding reception the decor and the people & food.
- Portraits vs arrival: portraits are shots the videographer sets up of the main people (the family with the \
baby, the couple) and holds long, usually 7 s or more; they can be playful rather than stiff. Arrival is \
candid: guests arriving, greeting, chatting, kids playing, and quick snapshots of about 5 s or less, even \
when guests smile at the lens. Decide with duration and who is in the shot; the posed/candid flag of the \
clip description is only a first guess.
- Each ceremony (catechism, sacrament / mystery, wedding service) is split in two parts sharing one name: \
ceremony_flow = the few long continuous main-camera takes that cover it start to end; ceremony_broll = \
every other clip filmed inside that ceremony window, from all cameras (faces, reactions, details, \
close-ups, kids with candles, dressing). Long masters never go to b-roll.
- All drone (aerial) clips go to one part of kind drone, labelled DRONE.
- kind unusable only for clips in which no frame shows anything of the event: black, only floor or ground, \
white sky, lens cap. Short, blurry, shaky, obstructed or accidental-looking clips that still show people or \
the place stay in the part they belong to: the videographer keeps them there. Most events have no unusable \
part; then leave it out.
- Labels: Greek, upper case, short, like «ΣΤΟΛΙΣΜΟΣ & CANDY BAR», «ΕΞΩΤΕΡΙΚΑ ΕΚΚΛΗΣΙΑΣ», \
«ΛΕΠΤΟΜΕΡΕΙΕΣ (ΡΟΥΧΑ, ΛΑΜΠΑΔΑ, ΛΑΔΟΠΑΝΟ)», «ΠΟΡΤΡΕΤΑ ΟΙΚΟΓΕΝΕΙΑΣ (ΠΡΙΝ)», «ΑΦΙΞΗ ΚΑΛΕΣΜΕΝΩΝ», \
«ΚΕΡΑΣΜΑ ΕΞΩ ΑΠΟ ΤΗΝ ΕΚΚΛΗΣΙΑ», «ΔΕΞΙΩΣΗ — ΧΩΡΟΣ & ΤΡΑΠΕΖΙΑ», «ΧΟΡΟΣ». For a ceremony pair give only the \
ceremony name (e.g. ΚΑΤΗΧΗΣΗ, ΜΥΣΤΗΡΙΟ) in `ceremony` and as label_el; the ΡΟΗ / B-ROLL suffix is added for you.
- No numbers in labels: numbering is done afterwards from the timeline.
- Assign every clip exactly once. confidence = how sure you are of that clip's part (0 to 1).

Answer only with the JSON object."""

AUDIO_RULES = """

Sound: each clip also carries what a local sound classifier and a speech recognizer heard in it: the share \
of the clip in which each sound group is heard, the room acoustics, and cue words (never the speech itself). \
Use it together with everything else: liturgy, chanting and the ritual cues (rings, crowning, isaiah, \
common_cup, renunciation, creed, immersion, gospel) place a clip inside that ceremony; wishes and toasts \
spoken to the camera mark wishes or interviews; music with crowd, applause or shouting marks the reception, \
an entrance or the dancing; a large hall acoustic means indoors (church or hall). Speech alone says little: \
people talk everywhere. Sound never overrides what the pictures clearly show."""

PARTIAL = """

In this run each clip is described only by: {what}. Build the structure from that alone."""


@dataclass
class Category:
    key: str
    number: int
    sub: str
    label_el: str
    folder: str
    description_el: str
    kind: str
    clips: list[str] = field(default_factory=list)
    parent: str = ""                           # key of the folder this one is the "a" part of (08 -> 08a)


@dataclass
class Structure:
    categories: list[Category]
    assignment: dict[str, str]                 # clip id -> category key
    confidence: dict[str, float]
    needs_review: list[str]
    notes: str = ""
    source: str = "ai"                          # ai | offline
    usage: dict = field(default_factory=dict)
    stars: list[str] = field(default_factory=list)
    edited: bool = False                        # the user changed it in Review

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Structure":
        return cls([Category(**c) for c in d["categories"]], d["assignment"], d["confidence"], d["needs_review"],
                   d.get("notes", ""), d.get("source", "ai"), d.get("usage", {}), d.get("stars", []),
                   d.get("edited", False))

    def folder_of(self, clip_id: str) -> str:
        key = self.assignment.get(clip_id)
        return next((c.folder for c in self.categories if c.key == key), "")


def camera_of(p: Project, c: Clip) -> str:
    dev = p.devices.get(c.device)
    return "drone" if dev and dev.kind == "drone" else ("main" if c.device == "A" else f"cam {c.device}")


def _columns(signals: frozenset) -> str:
    cols = ["index", "time", "duration"]
    if "camera" in signals:
        cols.append("camera")
    if "image" in signals:
        cols += ["moments", "location", "who", "shot flags", "description"]
    if "audio" in signals:
        cols.append("sound")
    return " | ".join(cols)


def _line(i: int, p: Project, c: Clip, d: dict, signals: frozenset = ALL_SIGNALS, sound: str = "") -> str:
    t = p.corrected(c)
    span = f"{t:%H:%M:%S}–{t + timedelta(seconds=c.duration):%H:%M:%S}" if t else "??"
    cells = [f"#{i}", span, fmt_duration(c.duration)]
    if "camera" in signals:
        cells.append(camera_of(p, c))
    if "image" in signals:
        if d.get("refused") or not d:
            cells.append("(no description available)")
        else:
            flags = [d.get("shot_type", ""), d.get("take", ""), "posed" if d.get("posed") else "candid"]
            if d.get("priest_in_vestments_at_font"):
                flags.append("priest_at_font")
            issues = ",".join(d.get("quality_issues") or [])
            cells += [",".join(d.get("moments") or []), d.get("location", ""), ",".join(d.get("people") or []) or "nobody",
                      " ".join(flags), d.get("description", "") + (f" (issues: {issues})" if issues else "")]
    if "audio" in signals:
        cells.append(f"sound: {sound or 'not analysed'}")
    return " | ".join(cells)


def _preset_text(preset: dict) -> str:
    parts = "\n".join(f"- {x['label']}" + (" (ceremony: ΡΟΗ + B-ROLL)" if x.get("split") else "")
                      + (f": {x['cues']}" if x.get("cues") else "") for x in preset.get("typical_parts", []))
    rules = "\n".join(f"- {r}" for r in preset.get("rules", []))
    return f"Typical parts (hints, not a fixed list):\n{parts}\n\nPreset rules:\n{rules}"


def _ceremony_name(part: dict) -> str:
    return (part.get("ceremony") or part["label_el"]).strip().upper()


def shows_nothing(d: dict) -> bool:
    """Pass-1 description of a clip with no picture of the event (the only kind that may go to 99)."""
    issues = set(d.get("quality_issues") or [])
    return "black" in issues or (not d.get("usable", True) and not d.get("people") and bool(issues & NOTHING_SHOWN))


def ordered_clips(p: Project, ids: list[str]) -> list[Clip]:
    return sorted((p.clips[i] for i in ids), key=lambda c: (p.corrected(c) or datetime.min, c.id))


def system_prompt(signals: frozenset = ALL_SIGNALS) -> str:
    text = SYSTEM + (AUDIO_RULES if "audio" in signals else "")
    if "image" not in signals:                       # ablation runs without the pictures
        text += PARTIAL.format(what=", ".join(s for s in SIGNALS if s in signals) + " (no pictures)")
    return text


def ai_structure(p: Project, descriptions: dict[str, dict], event_type: str, model: str = cost.DEFAULT_MODEL,
                 effort: str = "high", extra_notes: str = "", signals: frozenset = ALL_SIGNALS,
                 sound: dict[str, str] | None = None, ids: list[str] | None = None) -> tuple[dict, dict]:
    """Raw model answer (parts + assignments by clip index) and usage. `signals` limits what the
    model sees about each clip (time is always there); `sound` holds each clip's audio line."""
    signals = frozenset(signals) | {"time"}
    preset = config.load_preset(event_type)
    clips = ordered_clips(p, ids if ids is not None else list(descriptions))
    sound = sound or {}
    table = "\n".join(_line(i + 1, p, c, descriptions.get(c.id, {}), signals, sound.get(c.id, ""))
                      for i, c in enumerate(clips))
    user = (f"Event type: {event_type}. {len(clips)} clips on the corrected timeline "
            f"({_columns(signals)}):\n\n{table}\n\n"
            f"{_preset_text(preset)}\n\n{extra_notes}\nBuild the structure of this event and assign every clip "
            f"(use the clip numbers #1..#{len(clips)}).")
    client = credentials.client()
    t0 = time.time()
    with client.beta.messages.stream(
        model=model, max_tokens=64000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=system_prompt(signals), messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"structure call refused ({getattr(resp.stop_details, 'category', None)})")
    text = next(b.text for b in resp.content if b.type == "text")
    raw = json.loads(text)
    u = resp.usage
    usage = {"model": resp.model or model, "input": u.input_tokens, "output": u.output_tokens,
             "seconds": round(time.time() - t0, 1), "signals": sorted(signals)}
    raw["_order"] = [c.id for c in clips]
    return raw, usage


def finalize(p: Project, raw: dict, descriptions: dict[str, dict], preset: dict, source: str = "ai",
             signals: frozenset = ALL_SIGNALS) -> Structure:
    """Validate and number the model's answer (or the offline segmentation). The rules that need
    the camera (drone folder, main-camera masters, same-camera smoothing) run only when the camera
    is one of the signals, so that the ablation study measures each signal on its own."""
    camera = "camera" in signals
    order: list[str] = raw["_order"]
    parts = {x["id"]: dict(x) for x in raw["parts"]}
    assign: dict[str, str] = {}
    conf: dict[str, float] = {}
    for a in raw["assignments"]:
        idx = a["clip"] - 1
        if 0 <= idx < len(order) and a["part"] in parts and order[idx] not in assign:
            assign[order[idx]] = a["part"]
            conf[order[idx]] = float(a.get("confidence", 0.5))
    clips = ordered_clips(p, order)

    # 1. every clip exactly once: missing ones join their nearest neighbour in time
    for i, c in enumerate(clips):
        if c.id not in assign:
            near = next((clips[j].id for d in range(1, len(clips)) for j in (i - d, i + d)
                         if 0 <= j < len(clips) and clips[j].id in assign), None)
            if near:
                assign[c.id], conf[c.id] = assign[near], 0.3

    # 1b. 99 only for clips with no picture of the event; anything else rejoins its neighbours in time
    for i, c in enumerate(clips):
        if parts[assign[c.id]]["kind"] == UNUSABLE and not shows_nothing(descriptions.get(c.id, {})):
            keep = [j for d in range(1, len(clips)) for j in (i - d, i + d) if 0 <= j < len(clips)
                    and parts[assign[clips[j].id]]["kind"] != UNUSABLE]
            if keep:
                near = next((j for j in keep if clips[j].device == c.device), keep[0])
                assign[c.id], conf[c.id] = assign[clips[near].id], min(conf[c.id], 0.5)

    # 2. drone clips -> the drone part
    drone_ids = [c.id for c in clips if camera and p.devices.get(c.device) and p.devices[c.device].kind == "drone"]
    if drone_ids:
        dpart = next((k for k, x in parts.items() if x["kind"] == DRONE), None)
        if dpart is None:
            dpart = "drone"
            parts[dpart] = {"id": dpart, "label_el": "DRONE", "description_el": "Εναέρια πλάνα.", "kind": DRONE, "ceremony": ""}
        for cid in drone_ids:
            if parts[assign.get(cid, dpart)]["kind"] != UNUSABLE:
                assign[cid] = dpart

    # 3. ΡΟΗ / B-ROLL by the videographer's rule
    by_ceremony: dict[str, dict[str, str]] = {}
    for k, x in parts.items():
        if x["kind"] in (FLOW, BROLL):
            by_ceremony.setdefault(_ceremony_name(x), {})[x["kind"]] = k
    for name, pair in by_ceremony.items():
        for kind in (FLOW, BROLL):
            if kind not in pair:
                k = f"{name}-{kind}"
                parts[k] = {"id": k, "label_el": name, "description_el": "", "kind": kind, "ceremony": name}
                pair[kind] = k
        for c in clips:
            if assign.get(c.id) == pair[FLOW] and c.duration < BROLL_MAX_IN_FLOW_S:
                assign[c.id] = pair[BROLL]
            elif (assign.get(c.id) == pair[BROLL] and camera and c.device == "A" and c.duration >= 2 * FLOW_MIN_S
                  and descriptions.get(c.id, {}).get("take") == "continuous_take"):
                assign[c.id] = pair[FLOW]

    # 4. isolated low-confidence outliers between two neighbours of the same part (same camera only)
    seq = [c for c in clips if c.id not in drone_ids]
    for i in range(1, len(seq) - 1):
        a, c, b = seq[i - 1], seq[i], seq[i + 1]
        if (conf.get(c.id, 1) < 0.5 and assign[a.id] == assign[b.id] != assign[c.id]
                and parts[assign[a.id]]["kind"] == NORMAL and (not camera or a.device == c.device == b.device)):
            assign[c.id] = assign[a.id]

    # 5. numbering from the timeline: a ceremony pair shares one number (08 / 08a), unusable is 99
    first: dict[str, datetime] = {}
    for c in clips:
        t = p.corrected(c) or datetime.max
        k = assign.get(c.id)
        if k:
            group = _ceremony_name(parts[k]) if parts[k]["kind"] in (FLOW, BROLL) else k
            first[group] = min(first.get(group, datetime.max), t)
    style = preset["naming"]["greeklish_style"]
    sep = preset["naming"]["separator"]
    groups = sorted((g for g in first if not (g in parts and parts[g]["kind"] == UNUSABLE)), key=lambda g: first[g])
    cats: list[Category] = []
    for n, g in enumerate(groups, start=1):
        if g in by_ceremony:
            for kind, sub, suffix in ((FLOW, "", preset["naming"]["flow_suffix"]), (BROLL, "a", preset["naming"]["broll_suffix"])):
                k = by_ceremony[g][kind]
                label = f"{g}{sep}{suffix}"
                cats.append(Category(k, n, sub, label, folder_name(n, label, sub, style),
                                     parts[k].get("description_el", ""), kind,
                                     parent=by_ceremony[g][FLOW] if kind == BROLL else ""))
        else:
            x = parts[g]
            cats.append(Category(g, n, "", x["label_el"], folder_name(n, x["label_el"], "", style),
                                 x.get("description_el", ""), x["kind"]))
    for k, x in parts.items():
        if x["kind"] == UNUSABLE and any(v == k for v in assign.values()):
            u = preset["naming"]["unusable"]
            cats.append(Category(k, u["number"], "", u["label"], folder_name(u["number"], u["label"], "", style),
                                 x.get("description_el", ""), UNUSABLE))
    for cat in cats:
        cat.clips = [c.id for c in clips if assign.get(c.id) == cat.key]
    cats = [c for c in cats if c.clips]
    present = {c.key for c in cats}
    for cat in cats:                     # a B-ROLL without its ΡΟΗ is not an "a" part (06, not 06a)
        if cat.sub and cat.parent not in present:
            cat.sub, cat.parent = "", ""
            cat.folder = folder_name(cat.number, cat.label_el, "", style)
    review = [c.id for c in clips if conf.get(c.id, 0) < REVIEW_BELOW]
    return Structure(cats, {c: assign[c] for c in order if c in assign}, conf, review, raw.get("notes", ""), source)


RITUAL_CUES = {"liturgy", "crowning", "rings", "isaiah", "common_cup", "immersion", "renunciation", "creed", "gospel"}


def sound_context(a: dict) -> str:
    """service / party / other, from a clip's sound tags and cue words (offline sorting)."""
    from hypershutter.core import audio_tags
    if not a or a["tags"].get("missing") or a["tags"].get("no_audio"):
        return ""
    s = audio_tags.shares(a["tags"])
    if set(a.get("heard") or []) & RITUAL_CUES or s.get("chanting", 0) >= 0.25:
        return "service"
    lively = s.get("crowd", 0) + s.get("shouting", 0) + s.get("applause", 0) + s.get("singing", 0)
    if s.get("music", 0) >= 0.7 or (s.get("music", 0) >= 0.5 and lively >= 0.3):
        return "party"
    return "other"


def offline_structure(p: Project, ids: list[str], preset: dict, gap_minutes: float = 10.0,
                      sound: dict[str, dict] | None = None) -> Structure:
    """No API: new part at every big time gap; drone apart; long main-camera takes as ΡΟΗ inside a
    part. With `sound` (audio_tags results) a part is also split where the sound changes for a
    while: a service (chanting, liturgy, ritual cues) becomes a ceremony ΡΟΗ / B-ROLL pair, music
    with a lively crowd a party part."""
    clips = ordered_clips(p, ids)
    is_drone = {c.id: bool(p.devices.get(c.device) and p.devices[c.device].kind == "drone") for c in clips}
    ground = [c for c in clips if not is_drone[c.id]]
    # 1. time gaps
    gap_seg: dict[str, int] = {}
    seg, last_end = 0, None
    for c in ground:
        t = p.corrected(c)
        if last_end is None or (t and (t - last_end).total_seconds() > gap_minutes * 60):
            seg += 1
        gap_seg[c.id] = seg
        if t:
            end = t + timedelta(seconds=c.duration)
            last_end = end if last_end is None else max(last_end, end)
    # 2. sound context, smoothed over 5 neighbours; unknown sound takes its neighbours' context
    ctx = {c.id: sound_context((sound or {}).get(c.id, {})) for c in ground} if sound else {}
    smooth: dict[str, str] = {}
    for i, c in enumerate(ground):
        near = [ctx.get(ground[j].id, "") for j in range(max(0, i - 2), min(len(ground), i + 3))]
        votes = [x for x in near if x]
        smooth[c.id] = max(set(votes), key=lambda x: (votes.count(x), x == ctx.get(c.id))) if votes else "other"
    # 3. runs of (time segment, context); runs of fewer than 3 clips join the run before them
    runs: list[list] = []
    for c in ground:
        k = (gap_seg[c.id], smooth.get(c.id, "other"))
        if runs and runs[-1][0] == k:
            runs[-1][1].append(c)
        else:
            runs.append([k, [c]])
    merged: list[list] = []
    for k, cs in runs:
        if merged and (len(cs) < 3 and merged[-1][0][0] == k[0]):
            merged[-1][1] += cs
        else:
            merged.append([k, cs])
    parts: dict[str, dict] = {}
    assignments = []
    index = {c.id: i + 1 for i, c in enumerate(clips)}
    n_service = 0
    for n, ((g, context), cs) in enumerate(merged, start=1):
        if context == "service":
            n_service += 1
            name = f"ΤΕΛΕΤΗ {n_service}"
            for kind in (FLOW, BROLL):
                parts.setdefault(f"{name}-{kind}", {"id": f"{name}-{kind}", "label_el": name, "description_el": "",
                                                    "kind": kind, "ceremony": name})
            for c in cs:
                master = c.device == "A" and c.duration >= 2 * FLOW_MIN_S
                assignments.append({"clip": index[c.id], "part": f"{name}-{FLOW if master else BROLL}", "confidence": 0.4})
            continue
        key = f"seg{n}"
        label = "ΓΛΕΝΤΙ" if context == "party" else f"ΜΕΡΟΣ {n}"
        parts[key] = {"id": key, "label_el": label, "description_el": "", "kind": NORMAL, "ceremony": ""}
        assignments += [{"clip": index[c.id], "part": key, "confidence": 0.4} for c in cs]
    if any(is_drone.values()):
        parts["drone"] = {"id": "drone", "label_el": "DRONE", "description_el": "", "kind": DRONE, "ceremony": ""}
        assignments += [{"clip": index[c.id], "part": "drone", "confidence": 0.9} for c in clips if is_drone[c.id]]
    raw = {"parts": list(parts.values()), "assignments": assignments,
           "notes": "offline: time-gap" + (" + sound" if sound else "") + " segmentation", "_order": [c.id for c in clips]}
    return finalize(p, raw, {}, preset, source="offline")


FOLDER = re.compile(r"^(\d{2})([a-z]?) (.+)$")


def from_folders(p: Project) -> Structure:
    """The videographer's own organization as a Structure, for an event he has already sorted."""
    groups: dict[str, list[str]] = {}
    for c in p.clips.values():
        if c.kind == "video" and "/" in c.rel and FOLDER.match(c.rel.split("/", 1)[0]):
            groups.setdefault(c.rel.split("/", 1)[0], []).append(c.id)
    cats: list[Category] = []
    for top in sorted(groups):
        num, sub, label = FOLDER.match(top).groups()
        up = label.upper()
        kind = (FLOW if up.endswith("ΡΟΗ") else BROLL if "B-ROLL" in up else DRONE if "DRONE" in up
                else UNUSABLE if num == "99" else NORMAL)
        ids = [c.id for c in ordered_clips(p, groups[top])]
        cats.append(Category(top, int(num), sub, label, top, "", kind, ids))
    flows = {_ceremony_name({"label_el": c.label_el.split(" — ")[0]}): c.key for c in cats if c.kind == FLOW}
    for c in cats:
        if c.kind == BROLL:
            c.parent = flows.get(_ceremony_name({"label_el": c.label_el.split(" — ")[0]}), "")
    assign = {cid: c.key for c in cats for cid in c.clips}
    return Structure(cats, assign, {cid: 1.0 for cid in assign}, [], source="folders")
