"""Edit prep: B-roll lists and the two Premiere sequences, highlights and ροή.

Built from what the earlier stages know about each clip (corrected time, folder, the pass-1
description with its moments and notable times, resolution, frame rate) and the videographer's
editing rules (docs/workflow-editing.md). Only cutting and stitching: no colour, effects or
stabilisation. Everything here is a proposal the videographer finishes in Premiere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from hypershutter.core import frames, music
from hypershutter.core.media import Clip, fmt_duration
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, DRONE, FLOW, UNUSABLE, Category, Structure
from hypershutter.core.xmeml import FPS, Item, Marker, Media, Sequence

FLOOR_SKIP = 3.0              # the operator presses REC while walking: skip the first seconds
BAD = {"black", "blurry", "obstructed", "accidental", "dark"}
TENDER = {"baby", "mother", "father", "godparent", "grandparents", "grandmother", "grandfather", "bride", "groom"}
GROUPS = ("mum_baby", "crowd", "faces_family", "details")
GROUP_EL = {"mum_baby": "Μαμά / μωρό", "crowd": "Κόσμος / πλήθος", "faces_family": "Πρόσωπα / οικογένεια",
            "details": "Λεπτομέρειες"}
PRE = (("exterior", "ΕΞΩΤΕΡΙΚ"), ("interior", "ΕΣΩΤΕΡΙΚ"), ("details", "ΣΤΟΛΙΣΜ|ΛΕΠΤΟΜΕΡ|CANDY"),
       ("family", "ΠΟΡΤΡΕΤ|ΟΙΚΟΓΕΝ|ΕΤΟΙΜΑΣ"), ("guests", "ΑΦΙΞ|ΚΑΛΕΣΜ|ΚΟΣΜ"))
SHOT_ORDER = {"aerial": 0, "wide": 1, "mixed": 2, "medium": 3, "close_up": 4, "detail": 5}
DANCE = re.compile("ΧΟΡΟΣ|ΧΟΡΟΙ|DANCE", re.I)


# ---------------- what we know about each clip ----------------

@dataclass
class Shot:
    clip: Clip
    cat: Category
    desc: dict
    start: datetime | None
    media: Media

    @property
    def id(self) -> str:
        return self.clip.id

    @property
    def duration(self) -> float:
        return self.clip.duration

    @property
    def people(self) -> set[str]:
        return {p.lower() for p in self.desc.get("people") or []}

    @property
    def moments(self) -> set[str]:
        return set(self.desc.get("moments") or [])

    @property
    def issues(self) -> set[str]:
        return set(self.desc.get("quality_issues") or [])

    @property
    def shaky(self) -> bool:
        return "shaky" in self.issues

    @property
    def usable(self) -> bool:
        return self.desc.get("usable", True) and not (self.issues & {"black"}) and not self.desc.get("refused")

    @property
    def score(self) -> float:
        d = self.desc
        s = 1.0 + (1.0 if d.get("star") else 0) + 0.3 * min(3, len(d.get("notable") or []))
        s += 0.4 if not d.get("posed") else -0.2                 # candid over posed
        s -= 0.8 if self.shaky else 0
        s -= 1.5 * len(self.issues & BAD)
        return s

    @property
    def slow_ok(self) -> bool:
        """Slow motion only on details and tender close moments, and only from 50 fps sources."""
        tender = self.desc.get("shot_type") in ("close_up", "detail") or (
            self.people & TENDER and not self.desc.get("posed") and self.desc.get("shot_type") != "wide")
        return bool(tender) and self.media.fps >= 49 and self.cat.kind not in (DRONE, FLOW)

    def notable(self, pattern: str = "") -> list[float]:
        rx = re.compile(pattern, re.I) if pattern else None
        return [float(n["t"]) for n in self.desc.get("notable") or [] if not rx or rx.search(n.get("what", ""))]

    def window(self, length: float, prefer: float | None = None) -> float:
        """Source in-point for `length` seconds: around a notable moment, past the walking start."""
        dur = self.duration
        if length >= dur - 0.1:
            return 0.0
        lo = FLOOR_SKIP if dur - FLOOR_SKIP >= length + 0.5 else max(0.0, (dur - length) / 3)
        if prefer is None:
            nts = [t for t in self.notable() if lo <= t <= dur]
            prefer = nts[0] if nts else lo + (dur - lo) * 0.35
        return float(min(max(lo, prefer - length * 0.4), dur - length - 0.05))

    @property
    def group(self) -> str:
        """B-roll group the videographer lists: mum/baby, crowd, faces/family, details."""
        ppl = self.people
        if self.desc.get("shot_type") == "detail" or (self.moments & {"details", "decor", "food"} and not ppl - {"hands"}):
            return "details"
        shot = self.desc.get("shot_type")
        if "baby" in ppl and shot != "wide":
            return "mum_baby"
        if shot == "wide" or (shot == "mixed" and ppl & {"guests", "crowd"}):
            return "crowd"
        return "faces_family"


def media_of(p: Project, c: Clip) -> Media:
    pr = c.probe
    return Media(path=str(Path(p.root) / c.rel), duration=c.duration, fps=float(pr.get("fps") or 25),
                 width=int(pr.get("width") or 3840), height=int(pr.get("height") or 2160),
                 has_video=c.kind == "video", audio_channels=int(pr.get("channels") or 0) if pr.get("acodec") else 0)


def shots(p: Project, st: Structure, descs: dict[str, dict]) -> list[Shot]:
    out = []
    for cat in st.categories:
        if cat.kind == UNUSABLE:
            continue
        for cid in cat.clips:
            c = p.clips[cid]
            if c.kind != "video" or c.duration < 1.0:
                continue
            s = Shot(c, cat, descs.get(cid) or {}, p.corrected(c), media_of(p, c))
            if s.usable:
                out.append(s)
    return sorted(out, key=lambda s: (s.start or datetime.min, s.id))


# ---------------- B-roll lists (docs/workflow-organizing.md §5.4–5.5) ----------------

def ceremony_groups(st: Structure) -> list[tuple[str, list[Category]]]:
    """Ceremonies in order: (name, [ΡΟΗ category, B-ROLL category])."""
    out: dict[int, list[Category]] = {}
    for c in st.categories:
        if c.kind in (FLOW, BROLL):
            out.setdefault(c.number, []).append(c)
    return [(cats[0].label_el.split(" — ")[0], cats) for _, cats in sorted(out.items())]


def broll_list(p: Project, st: Structure, descs: dict[str, dict], keys: list[str]) -> dict:
    """B-roll of the given folders, grouped, strongest first, with resolution and rotation notes,
    plus candidate in/out points inside the long masters of those folders."""
    sh = [s for s in shots(p, st, descs) if s.cat.key in keys]
    groups: dict[str, list[dict]] = {g: [] for g in GROUPS}
    masters = []
    for s in sh:
        if s.cat.kind == FLOW:
            segs = [{"in": max(0.0, t - 1.5), "out": min(s.duration, t + 2.5), "what": n.get("what", "")}
                    for n in s.desc.get("notable") or [] for t in [float(n["t"])]]
            masters.append({"clip": s.clip.name, "time": f"{s.start:%H:%M:%S}" if s.start else "",
                            "duration": fmt_duration(s.duration), "segments": segs})
            continue
        notes = []
        if s.media.width < 3840:
            notes.append(f"{s.media.height}p → scale {3840 / s.media.width * 100:.0f}%")
        if s.clip.probe.get("rotation"):
            notes.append(f"rotate {s.clip.probe['rotation']}°")
        if s.shaky:
            notes.append("shaky (Warp)")
        groups[s.group].append({"clip": s.clip.name, "time": f"{s.start:%H:%M:%S}" if s.start else "",
                                "duration": fmt_duration(s.duration), "camera": s.clip.device,
                                "star": bool(s.desc.get("star")) or s.score >= 2.6, "score": round(s.score, 2),
                                "notes": notes, "desc": s.desc.get("description_el") or s.desc.get("description", "")})
    for g in groups.values():
        g.sort(key=lambda r: -r["score"])
    return {"groups": groups, "masters": masters}


def broll_markdown(title: str, bl: dict) -> str:
    lines = [f"# B-roll — {title}", ""]
    for g in GROUPS:
        rows = bl["groups"][g]
        if not rows:
            continue
        lines += [f"## {GROUP_EL[g]} ({len(rows)})", "", "| clip | κάμ. | ώρα | διάρκεια | σημειώσεις | τι δείχνει |", "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| `{r['clip']}`{' ⭐' if r['star'] else ''} | {r['camera']} | {r['time']} | {r['duration']} | "
                         f"{', '.join(r['notes'])} | {r['desc']} |")
        lines.append("")
    if bl["masters"]:
        lines += ["## Μέσα στα μεγάλα πλάνα (in → out, κατά προσέγγιση: έλεγξέ τα)", ""]
        for m in bl["masters"]:
            lines.append(f"**`{m['clip']}`** {m['time']} · {m['duration']}")
            lines += [f"- {fmt_duration(s['in'])} → {fmt_duration(s['out'])} {s['what']}" for s in m["segments"]]
            if not m["segments"]:
                lines.append("- δεν σπάει πουθενά το κάδρο")
            lines.append("")
    return "\n".join(lines)


# ---------------- drone windows that move ----------------

def _thumb(path: str) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("L").resize((160, 90)), dtype=np.float32) / 255.0


def drone_window(s: Shot, length: float) -> tuple[float, float]:
    """(in-point, motion score): a stretch with steady, clear change (orbit, push, reveal), not a hover."""
    fr = frames.load_cached(s.clip, frames.FrameSettings()) or []
    fr = [f for f in fr if not f.scene] or fr
    if len(fr) < 3 or s.duration <= length + 1:
        return s.window(length), 0.0
    th = [_thumb(f.path) for f in fr]
    change = np.array([float(np.abs(a - b).mean()) for a, b in zip(th, th[1:])])
    step = max(1, round(length / max(0.5, fr[1].t - fr[0].t)))
    best, best_t = -1e9, fr[0].t
    for i in range(0, max(1, len(change) - step + 1)):
        seg = change[i:i + step]
        score = seg.mean() - 0.8 * seg.std() - 2.0 * max(0.0, seg.max() - 0.12)   # steady and moving, no whip
        if score > best:
            best, best_t = score, fr[i].t
    return float(min(best_t, s.duration - length - 0.05)), float(best)


# ---------------- highlights ----------------

@dataclass
class Cut:
    shot: Shot
    slot: int
    src_in: float
    speed: float = 1.0
    note: str = ""


@dataclass
class Highlights:
    grid: music.Grid
    cuts: list[Cut]
    song: Media
    film: dict[str, Cut] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _pre_pools(pre: list[Shot]) -> dict[str, list[Shot]]:
    pools: dict[str, list[Shot]] = {k: [] for k, _ in PRE}
    pools["other"] = []
    for s in pre:
        key = next((k for k, rx in PRE if re.search(rx, s.cat.label_el)), "other")
        pools[key].append(s)
    return pools


def _spread(cands: list[Shot], n: int, must: list[Shot] = ()) -> list[Shot]:
    """n shots spread over the time span, best-scored in each stretch, keeping `must` ones."""
    if n <= 0 or not cands:
        return []
    cands = sorted(cands, key=lambda s: (s.start or datetime.min, s.id))
    chosen = list(dict.fromkeys(must))[:n]
    rest = [s for s in cands if s not in chosen]
    buckets = np.array_split(np.arange(len(rest)), max(1, min(n - len(chosen), len(rest)))) if rest else []
    for b in buckets:
        if len(chosen) >= n:
            break
        if len(b):
            chosen.append(max((rest[i] for i in b), key=lambda s: s.score))
    return sorted(chosen, key=lambda s: (s.start or datetime.min, s.id))


def build_highlights(p: Project, st: Structure, descs: dict[str, dict], song: Path, template: dict) -> Highlights:
    a = music.analyse(song)
    grid = music.fit(template, a)
    song_media = Media(path=str(song), duration=a["duration"], has_video=False, audio_channels=2)
    allshots = [s for s in shots(p, st, descs) if not (s.issues & BAD)]
    drones = [s for s in allshots if s.cat.kind == DRONE]
    ceremonies = ceremony_groups(st)
    first_cer = min((c.number for _, cats in ceremonies for c in cats), default=10**6)
    last_cer = max((c.number for _, cats in ceremonies for c in cats), default=-1)
    pre = [s for s in allshots if s.cat.kind not in (DRONE, FLOW, BROLL) and s.cat.number < first_cer]
    post = [s for s in allshots if s.cat.kind not in (DRONE, FLOW, BROLL) and s.cat.number > last_cer]
    n = len(grid.slots)
    idx = {k: grid.index_at(v) for k, v in grid.marks.items()}
    title_i, intro_i = idx.get("title", 3), idx.get("intro_end", int(n * 0.47))
    film1_i, film2_i, end_i = idx.get("film1", int(n * 0.55)), idx.get("film2", int(n * 0.7)), idx.get("end_montage", int(n * 0.81))
    plan: dict[int, Shot] = {}
    prefer: dict[int, float] = {}
    used: set[str] = set()
    warnings: list[str] = []

    # drones: establishing at the start, title over a clean wide one, between sections, last slot
    drone_slots = list(range(0, title_i + 1)) + [intro_i, min(film2_i - 1, film1_i + 4), end_i - 1, n - 1]
    drone_slots = sorted(set(i for i in drone_slots if 0 <= i < n))
    ranked = sorted(drones, key=lambda s: -s.score)
    order = sorted(drones, key=lambda s: (s.start or datetime.min))
    for i in drone_slots:
        if not drones:
            break
        if i == n - 1:
            pick = order[-1]                                   # the last, widest look back at the day
        else:
            pool = [s for s in (ranked if i <= title_i else order) if s.id not in used] or ranked
            pick = pool[0]
        plan[i] = pick
        used.add(pick.id)
    if not drones:
        warnings.append("no drone footage: drone slots use other shots")

    # pre-ceremony: exterior → interior → details (wide first) → family → guests
    pre_slots = [i for i in range(title_i + 1, intro_i) if i not in plan]
    pools = _pre_pools(pre)
    weights = {"exterior": 0.12, "interior": 0.12, "details": 0.34, "family": 0.21, "guests": 0.21}
    avail = {k: v for k, v in pools.items() if v and k in weights}
    total_w = sum(weights[k] for k in avail) or 1
    counts = {k: min(len(avail[k]), max(1, round(len(pre_slots) * weights[k] / total_w))) for k in avail}
    while sum(counts.values()) > len(pre_slots):
        counts[max(counts, key=counts.get)] -= 1
    for key in ("details", "family", "guests", "exterior", "interior"):       # fill what is left, in this order
        while key in counts and sum(counts.values()) < len(pre_slots) and counts[key] < len(avail[key]):
            counts[key] += 1
    seq: list[Shot] = []
    for key in ("exterior", "interior", "details", "family", "guests"):
        if key not in avail:
            continue
        chosen = _spread([s for s in avail[key] if s.id not in used], counts[key])
        if key in ("details", "exterior", "interior"):
            chosen.sort(key=lambda s: SHOT_ORDER.get(s.desc.get("shot_type"), 3))
        seq += chosen
    extra = sorted((s for s in pre if s.id not in {x.id for x in seq}), key=lambda s: -s.score)
    seq += extra[: max(0, len(pre_slots) - len(seq))]
    for i, s in zip(pre_slots, seq):
        plan[i] = s

    # ceremonies: beats in time order around their film scene; the mystery always contains the immersion
    film_cuts: dict[str, Cut] = {}
    if ceremonies:
        drone_mid = min(film2_i - 1, film1_i + 4)
        if len(ceremonies) > 1:
            segs = [(ceremonies[0], "film1", film1_i, range(intro_i + 1, drone_mid)),
                    (ceremonies[-1], "film2", film2_i, range(drone_mid + 1, end_i - 1))]
        else:
            segs = [(ceremonies[0], "film2", film2_i, range(intro_i + 1, end_i - 1))]
        for (name, cats), key, film_slot, slot_range in segs:
            keys = {c.key for c in cats}
            masters = [s for s in allshots if s.cat.key in keys and s.cat.kind == FLOW]
            broll = [s for s in allshots if s.cat.key in keys and s.cat.kind == BROLL and s.id not in used]
            film = _film_moment(masters, key)
            film_time = None
            if film and film_slot in slot_range:
                m, t = film
                film_cuts[key] = Cut(m, film_slot, m.window(grid.slot_len(film_slot), t))
                plan[film_slot] = m
                film_time = m.start + timedelta(seconds=t) if m.start else None
            moments = [_Moment(b, None) for b in broll if b.start]
            moments += [_Moment(m, t) for m in masters if m.start for t in m.notable() if t > FLOOR_SKIP
                        and not (film and m.id == film[0].id and abs(t - film[1]) < 10)]
            slots_ = [i for i in slot_range if i not in plan]
            if film_time is not None:
                before = [i for i in slots_ if i < film_slot]
                after = [i for i in slots_ if i > film_slot]
                parts = [(before, [x for x in moments if x.when < film_time - timedelta(seconds=2)]),
                         (after, [x for x in moments if x.when > film_time + timedelta(seconds=2)])]
            else:
                parts = [(slots_, moments)]
            for part_slots, cands in parts:
                must = [x for x in cands if x.shot.cat.kind == BROLL and "immersion" in x.shot.moments][:1]
                chosen = _pick_moments(cands, len(part_slots), must)
                chosen = _no_master_repeats(chosen, cands, plan.get(film_slot) if film_time else None,
                                            [x for x in moments if x.shot.id not in used])
                for i, x in zip(part_slots, chosen):
                    plan[i] = x.shot
                    if x.t is not None:
                        prefer[i] = x.t
                    used.add(x.shot.id)
            empty = [i for i in slot_range if i not in plan]
            if empty:                                  # too little footage on one side of the film scene
                spare = sorted([x for x in moments if x.shot.id not in used or x.t is not None]
                               + [_Moment(m, float(t)) for m in masters if m.start
                                  for t in np.arange(FLOOR_SKIP + 5, m.duration - 5, 30.0)], key=lambda x: x.when)
                fill = _no_master_repeats(_pick_moments(spare, len(empty), []), spare, None,
                                          [x for x in moments if x.t is None and x.shot.id not in used])
                for i, x in zip(empty, fill):
                    plan[i] = x.shot
                    if x.t is not None:
                        prefer[i] = x.t
                    used.add(x.shot.id)
            if key == "film2" and "film2" not in film_cuts and not any(
                    "immersion" in plan[i].moments for i in slot_range if i in plan):
                warnings.append("the immersion was not found: check the μυστήριο beats")

    # end montage: κέρασμα, reception, kids, music, dance in time order; baby with parents near the end
    end_slots = [i for i in range(end_i, n - 1) if i not in plan]
    post_pool = [s for s in post if s.id not in used]
    family_end = [s for s in post_pool if "baby" in s.people and s.people & {"mother", "father"}][-1:]
    chosen = _spread([s for s in post_pool if s not in family_end], max(0, len(end_slots) - len(family_end)))
    chosen += family_end
    for i, s in zip(end_slots, chosen):
        plan[i] = s
        used.add(s.id)

    # cuts with windows; slow motion only where the rules allow it; a master never shows the same moment twice
    cuts: list[Cut] = []
    taken_windows: dict[str, list[tuple[float, float]]] = {}
    for c in film_cuts.values():
        taken_windows.setdefault(c.shot.id, []).append((c.src_in, c.src_in + grid.slot_len(c.slot)))
    for i in range(n):
        s = plan.get(i)
        if s is None:
            warnings.append(f"slot {i + 1} ({grid.slots[i]:.2f}s) is empty: not enough footage")
            continue
        fc = next((c for c in film_cuts.values() if c.slot == i), None)
        if fc:
            cuts.append(fc)
            continue
        speed = grid.slow.get(i, 1.0) if s.slow_ok else 1.0
        length = grid.slot_len(i) * speed
        note = "needs Warp" if s.shaky else ""
        if s.duration < length + 0.15:
            alt = _replacement(s, length, allshots, used)
            if alt is not None:
                s, speed = alt, 1.0
                used.add(s.id)
            else:                                   # slow it just enough to fill the slot
                speed = max(0.5, (s.duration - 0.15) / grid.slot_len(i))
                note = (note + "; " if note else "") + f"slowed to {speed:.0%} to fill the slot"
            length = grid.slot_len(i) * speed
        if s.cat.kind == DRONE:
            src_in, _ = drone_window(s, length)
        elif s.cat.kind == FLOW:
            src_in = _free_window(s, length, prefer.get(i), taken_windows.setdefault(s.id, []))
            taken_windows[s.id].append((src_in, src_in + length))
        else:
            src_in = s.window(length, prefer.get(i))
        cuts.append(Cut(s, i, src_in, speed, note))
    return Highlights(grid, cuts, song_media, film_cuts, warnings)


@dataclass
class _Moment:
    shot: Shot
    t: float | None                     # a moment inside a master; None = the b-roll clip itself

    @property
    def when(self) -> datetime:
        off = self.t if self.t is not None else min(self.shot.duration * 0.4, FLOOR_SKIP + 1)
        return self.shot.start + timedelta(seconds=off)

    @property
    def score(self) -> float:
        return self.shot.score + (0.3 if self.t is not None else 0.0)


def _film_moment(masters: list[Shot], key: str) -> tuple[Shot, float] | None:
    """FILM 1: the naming phrase late in the catechism; FILM 2: the immersion in the mystery."""
    rx = r"name|creed|godparent|πιστε|όνομα" if key == "film1" else r"immers|dip|βουτ|βάπτ|baptiz"
    hits = [(s, t) for s in masters for t in s.notable(rx)]
    if key == "film2" and not hits:
        hits = [(s, t) for s in masters if "immersion" in s.moments for t in s.notable()[:1]]
    if not hits and masters:
        m = masters[-1] if key == "film1" else max(masters, key=lambda s: s.duration)
        hits = [(m, m.duration * (0.8 if key == "film1" else 0.5))]
    if not hits:
        return None
    return hits[-1] if key == "film1" else hits[0]


def _pick_moments(cands: list[_Moment], n: int, must: list[_Moment]) -> list[_Moment]:
    """n moments spread over the time span (best in each stretch), in time order."""
    if n <= 0 or not cands:
        return []
    cands = sorted(cands, key=lambda x: x.when)
    chosen = list(must[:n])
    rest = [x for x in cands if x not in chosen]
    k = n - len(chosen)
    if rest and k > 0:
        for b in np.array_split(np.arange(len(rest)), min(k, len(rest))):
            pool = [rest[i] for i in b if all(rest[i].shot.id != c.shot.id or rest[i].t is not None for c in chosen)]
            if pool:
                chosen.append(max(pool, key=lambda x: x.score))
    return sorted(chosen, key=lambda x: x.when)


def _no_master_repeats(chosen: list[_Moment], cands: list[_Moment], film_shot: Shot | None,
                       spare: list[_Moment] = ()) -> list[_Moment]:
    """Never two pieces of the same master back to back (the film scene next door counts too):
    the second one becomes the nearest unused b-roll in time."""
    out = list(chosen)
    taken = {x.shot.id for x in out}
    for i, x in enumerate(out):
        if x.t is None:
            continue
        neighbours = {out[i - 1].shot.id} if i else set()
        if film_shot is not None and i in (0, len(out) - 1):
            neighbours.add(film_shot.id)
        if x.shot.id not in neighbours:
            continue
        alts = ([c for c in cands if c.t is None and c.shot.id not in taken]
                or [c for c in spare if c.shot.id not in taken and c.shot.id not in neighbours | {x.shot.id}])
        if alts:
            alt = min(alts, key=lambda c: abs((c.when - x.when).total_seconds()))
            out[i] = alt
            taken.add(alt.shot.id)
        else:                                    # no spare b-roll: swap with the next different shot
            j = next((j for j in range(i + 1, len(out)) if out[j].shot.id not in neighbours | {x.shot.id}), None)
            if j is not None:
                out[i], out[j] = out[j], out[i]
    return out


def _replacement(s: Shot, length: float, allshots: list[Shot], used: set[str]) -> Shot | None:
    """A long-enough unused shot from the same folder, else from a neighbouring folder."""
    for same in (lambda x: x.cat.key == s.cat.key, lambda x: abs(x.cat.number - s.cat.number) <= 1):
        pool = [x for x in allshots if same(x) and x.id not in used and x.duration >= length + 0.3
                and x.cat.kind == s.cat.kind]
        if pool:
            return max(pool, key=lambda x: x.score)
    return None


def _free_window(s: Shot, length: float, prefer: float | None, taken: list[tuple[float, float]]) -> float:
    """An in-point whose window does not overlap moments of this master already used (2 s apart)."""
    def free(a: float) -> bool:
        return all(a + length + 2 <= x or a >= y + 2 for x, y in taken)
    starts = ([s.window(length, prefer)] if prefer is not None else []) + [s.window(length, t) for t in s.notable()]
    starts += list(np.linspace(min(FLOOR_SKIP, s.duration / 3), max(0.0, s.duration - length - 0.1), 40))
    return float(next((a for a in starts if free(a)), starts[0]))


def highlights_sequence(name: str, hl: Highlights) -> Sequence:
    g = hl.grid
    seq = Sequence(name, video=[[]], audio=[[], [], []])
    for c in hl.cuts:
        start = round(g.slots[c.slot] * FPS)
        end = round((g.slots[c.slot + 1] if c.slot + 1 < len(g.slots) else g.end) * FPS)
        seq.video[0].append(Item(c.shot.media, start, end, c.src_in, c.speed))
    end = round(g.end * FPS)
    for ch in (1, 2):
        seq.audio[ch - 1].append(Item(hl.song, 0, end, 0.0, channel=ch, fade_out=30))
    for key, label in (("film1", "FILM 1 – κατήχηση: η φράση με το όνομα (ήχος κάμερας στο A3) — έλεγξε το σημείο"),
                       ("film2", "FILM 2 – βουτιά: «Βαπτίζεται ο δούλος του Θεού…» (ήχος κάμερας στο A3) — έλεγξε το σημείο")):
        c = hl.film.get(key)
        if c and c.shot.media.audio_channels:
            start = round(g.slots[c.slot] * FPS)
            stop = round((g.slots[c.slot + 1] if c.slot + 1 < len(g.slots) else g.end) * FPS)
            seq.audio[2].append(Item(c.shot.media, start, stop, c.src_in, channel=1, fade_in=8, fade_out=12))
            seq.markers.append(Marker(label, start))
    if "title" in g.marks:
        seq.markers.insert(0, Marker("ΤΙΤΛΟΣ (κείμενο πάνω στο drone)", round(g.marks["title"] * FPS)))
    for c in hl.cuts:
        if c.note:
            seq.markers.append(Marker(f"{c.shot.clip.name}: {c.note}", round(g.slots[c.slot] * FPS)))
    return seq


# ---------------- ροή ----------------

@dataclass
class Flow:
    seq: Sequence
    warnings: list[str] = field(default_factory=list)
    minutes: float = 0.0


def _master_in(s: Shot) -> float:
    return FLOOR_SKIP if s.issues & {"floor_or_ground", "shaky", "accidental"} else 1.0


def build_flow(name: str, p: Project, st: Structure, descs: dict[str, dict], hl: Highlights,
               mic: Clip | None = None) -> Flow:
    seq = Sequence(name, video=[[], []], audio=[[], [], []])
    warnings = ["the off-ritual talk is not cut yet (needs a transcript): trim it in Premiere"]
    g = hl.grid
    allshots = shots(p, st, descs)
    intro_end = round(g.marks.get("intro_end", g.end * 0.46) * FPS)

    # intro = the highlights before the ceremony, music fading out under the first ceremony seconds
    for c in hl.cuts:
        start = round(g.slots[c.slot] * FPS)
        end = round((g.slots[c.slot + 1] if c.slot + 1 < len(g.slots) else g.end) * FPS)
        if start < intro_end:
            seq.video[0].append(Item(c.shot.media, start, min(end, intro_end), c.src_in, c.speed))
    fade = 16 * FPS
    for ch in (1, 2):
        seq.audio[ch].append(Item(hl.song, 0, intro_end + fade, 0.0, channel=ch, fade_out=fade))
    if "title" in g.marks:
        seq.markers.append(Marker("ΤΙΤΛΟΣ", round(g.marks["title"] * FPS)))
    t = intro_end
    used: set[str] = set()

    def put(s: Shot, src_in: float, length: float, audio: bool = True) -> int:
        nonlocal t
        frames_ = max(1, round(length * FPS))
        seq.video[0].append(Item(s.media, t, t + frames_, src_in))
        if audio and s.media.audio_channels:
            seq.audio[0].append(Item(s.media, t, t + frames_, src_in, channel=1, fade_in=6, fade_out=6))
        t += frames_
        used.add(s.id)
        return t - frames_

    for name_, cats in ceremony_groups(st):
        keys = {c.key for c in cats}
        masters = sorted((s for s in allshots if s.cat.key in keys and s.cat.kind == FLOW), key=lambda s: s.start or datetime.min)
        broll = [s for s in allshots if s.cat.key in keys and s.cat.kind == BROLL]
        if not masters:
            warnings.append(f"{name_}: no ΡΟΗ masters, only b-roll")
            continue
        seq.markers.append(Marker(f"{name_} — Impact Dissolve", t))
        placed: list[tuple[Shot, int, float, float]] = []          # master, seq start, src in, src out
        prev_end_time = None
        for m in masters:
            src_in = _master_in(m)
            if prev_end_time and m.start:
                overlap = (prev_end_time - m.start).total_seconds()
                src_in = max(src_in, overlap) if overlap > 0 else src_in
                gap = -overlap
                bridge = [b for b in broll if b.start and prev_end_time < b.start < m.start and not b.shaky]
                if gap > 20 and bridge:                               # camera was off: b-roll with its own sound
                    seq.markers.append(Marker("κάμερα σβηστή — b-roll με δικό του ήχο (Impact Dissolve)", t))
                    total = 0.0
                    for b in bridge:
                        if total >= 35:
                            break
                        length = min(b.duration - 0.2, max(3.0, min(8.0, b.duration)))
                        put(b, b.window(length), length)
                        total += length
            if src_in >= m.duration - 2:
                continue
            start = put(m, src_in, m.duration - src_in - 0.3)
            placed.append((m, start, src_in, m.duration - 0.3))
            prev_end_time = m.start + timedelta(seconds=m.duration) if m.start else None
            imm = [x for x in m.notable(r"immers|dip|βουτ") if x > src_in]
            if imm:
                seq.markers.append(Marker("ΒΟΥΤΙΑ", start + round((imm[0] - src_in) * FPS)))

        _cutaways(seq, placed, broll, used, [mk.at for mk in seq.markers if mk.name == "ΒΟΥΤΙΑ"])

    # ending: a moving drone, then the highlights' end montage on the same music, then drones
    seq.markers.append(Marker("ΤΕΛΟΣ ΤΕΛΕΤΗΣ – drone + κέρασμα/δεξίωση με μουσική", t))
    drones = [s for s in allshots if s.cat.kind == DRONE]
    end_m = g.marks.get("end_montage", g.end * 0.83)
    drone_len = 6.0
    music_start = t
    if drones:
        d = drones[0] if drones[0].id not in used else drones[-1]
        src, _ = drone_window(d, drone_len)
        put(d, src, drone_len, audio=False)
    song_offset = max(0.0, end_m - drone_len)
    for c in hl.cuts:
        if g.slots[c.slot] >= end_m and c.slot < len(g.slots) - 1:
            length = g.slot_len(c.slot)
            seq.video[0].append(Item(c.shot.media, t, t + round(length * FPS), c.src_in, c.speed))
            t += round(length * FPS)
    tail = hl.song.duration - (song_offset + (t - music_start) / FPS)
    if tail > 1.0 and drones:
        d = drones[-1]
        src, _ = drone_window(d, min(tail, d.duration - 0.2))
        put(d, src, min(tail, d.duration - src - 0.1), audio=False)
    music_len = min(t - music_start, round((hl.song.duration - song_offset) * FPS))
    for ch in (1, 2):
        seq.audio[ch].append(Item(hl.song, music_start, music_start + music_len, song_offset, channel=ch,
                                  fade_in=12 * FPS, fade_out=2 * FPS))

    # dances in full, own camera audio, a marker at every join, then a moving drone
    dances = [s for s in allshots if DANCE.search(s.cat.label_el) and s.duration > 20]
    if dances:
        seq.markers.append(Marker("ΧΟΡΟΙ – ολόκληροι, ήχος από την κάμερα (Impact Dissolve σε κάθε αλλαγή)", t))
        for k, d in enumerate(dances):
            if k:
                seq.markers.append(Marker("Impact Dissolve", t))
            put(d, 2.0, d.duration - 4.0)
        if drones:
            dr = drones[-1]
            src, _ = drone_window(dr, 6.0)
            put(dr, src, 6.0, audio=False)

    if mic is not None:
        warnings.append("a lapel-mic recording exists: A1 still uses camera audio; put the mic under the ceremony in Premiere")
    return Flow(seq, warnings, round(t / FPS / 60, 1))


CUT_EVERY = 45.0              # s between cutaways inside a master
CUT_LEN = 2.4                 # s per cutaway (1-3 s, never long chains)


def _cutaways(seq: Sequence, placed: list[tuple[Shot, int, float, float]], broll: list[Shot], used: set[str],
              immersion: list[int]) -> None:
    """V2 cutaways: one over every join between masters, then one every ~45 s; none over the immersion.
    A second-camera clip filmed during a master goes at its true time (multicam); other b-roll is the
    unused, steady clip filmed closest in time. No b-roll is used twice in the ροή."""
    spots: list[tuple[int, datetime | None, bool]] = []          # seq frame, real time there, is a join
    for k, (m, mstart, mi, mo) in enumerate(placed):
        if k:
            spots.append((mstart - round(CUT_LEN / 2 * FPS), m.start + timedelta(seconds=mi) if m.start else None, True))
        x = mi + CUT_EVERY
        while x < mo - CUT_EVERY / 2:
            spots.append((mstart + round((x - mi) * FPS), m.start + timedelta(seconds=x) if m.start else None, False))
            x += CUT_EVERY
    pool = [b for b in broll if b.id not in used and not b.shaky and b.start and b.duration >= CUT_LEN + 0.5]
    # second camera inside a master: at its true time
    for b in [b for b in pool if b.clip.device != placed[0][0].clip.device]:
        for m, mstart, mi, mo in placed:
            at = (b.start - m.start).total_seconds() if m.start else -1
            src = min(FLOOR_SKIP, max(0.0, b.duration - CUT_LEN - 0.1))
            if mi + 2 <= at + src <= mo - CUT_LEN - 2:
                pos = mstart + round((at + src - mi) * FPS)            # the same instant as the master
                if all(abs(pos - x) > 10 * FPS for x in immersion):
                    seq.video[1].append(Item(b.media, pos, pos + round(CUT_LEN * FPS), src))
                    used.add(b.id)
                break
    for pos, when, join in spots:
        if any(abs(pos - x) < 10 * FPS for x in immersion):
            continue
        if not join and any(abs(pos - it.start) < 20 * FPS for it in seq.video[1]):
            continue
        cands = [b for b in pool if b.id not in used]
        if not cands or when is None:
            continue
        b = min(cands, key=lambda c: abs((c.start - when).total_seconds()) - 20 * c.score)
        seq.video[1].append(Item(b.media, pos, pos + round(CUT_LEN * FPS), b.window(CUT_LEN)))
        used.add(b.id)
    seq.video[1].sort(key=lambda i: i.start)
    _drop_overlaps(seq.video[1])


def _drop_overlaps(track: list[Item]) -> None:
    keep: list[Item] = []
    for it in sorted(track, key=lambda i: i.start):
        if keep and it.start < keep[-1].end:
            continue
        keep.append(it)
    track[:] = keep
