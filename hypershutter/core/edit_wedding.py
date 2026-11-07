"""Wedding highlights, modelled on the videographer's own wedding edit (docs/wedding-reference-edit.md).

Teaser (best moments of the whole day) → title marker on a clean shot → the place → details and
getting ready (bride and groom intercut, live-sound moments) → church & arrival → ceremony →
exit & wishes → couple shoot → (baptism and family with the baby) → reception → party → final
drone. Each part runs on one of his songs, cut on the song's beat; songs crossfade. Film scenes
carry the moment's live sound and the projector SFX over a ducked song; ambiences and whooshes
come from his own library. Only cutting and sound: the titles, film overlays, grading and
effects stay his.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from hypershutter.core import library, music
from hypershutter.core.edit import BAD, FLOOR_SKIP, Shot, drone_window, shots
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, DRONE, FLOW, Structure
from hypershutter.core.xmeml import FPS, Item, Marker, Media, Sequence

# part, song role, target seconds, shot length seconds
PARTS = [("teaser", "intro", 22.0, 2.2), ("title", "intro", 4.5, 4.5), ("place", "intro", 4.0, 1.2),
         ("prep", "intro", 46.0, 1.3), ("church", "story", 42.0, 2.0), ("ceremony", "ceremony", 34.0, 1.4),
         ("exit", "ceremony", 7.0, 1.4), ("couple", "ceremony", 8.0, 1.8), ("baptism", "ceremony", 40.0, 1.5),
         ("reception", "party", 20.0, 1.3), ("party", "party", 62.0, 1.15), ("final", "party", 6.0, 6.0)]
LABELS = [("interviews", r"ΣΥΝΕΝΤΕΥΞ|ΜΙΛΑΕΙ ΣΤΗΝ"), ("other_day", r"STUDIO|\(\d\d-\d\d\)"),
          ("place", r"ΧΩΡΙΟ|ΤΟΠΟΘΕΣ"), ("prep", r"ΛΕΠΤΟΜΕΡ|ΕΤΟΙΜΑΣ"), ("exit", r"ΕΞΟΔΟΣ"),
          ("couple", r"ΦΩΤΟΓΡΑΦΗΣΗ ΖΕΥΓ|ΖΕΥΓΑΡΙ"), ("baptism", r"ΒΑΦΤΙΣ|ΜΩΡΟ|ΟΙΚΟΓΕΝΕΙΑΚ"),
          ("reception", r"ΔΕΞΙΩΣ"), ("party", r"ΧΟΡΟΣ|ΧΟΡΟΙ|ΠΑΡΤΙ"), ("ceremony", r"ΓΑΜΟΣ"),
          ("church", r"ΕΚΚΛΗΣΙΑ|ΑΦΙΞΗ")]
DRONE_BEFORE = {"church", "baptism", "reception"}           # a drone opens these parts
FILM_PARTS = {"church": 1, "ceremony": 1, "couple": 1, "baptism": 2}
LIVE_PARTS = {"prep": 2}                                   # live-sound moments without the film look
FILM_LEN = 4.2
LIVE_LEN = 4.0
FILM_RX = {"ceremony": r"ring|crown|στέφ|cup|ποτήρ|vow|kiss|isaiah|ησαΐα|dance around",
           "baptism": r"immers|dip|βουτ|baptiz|anoint|λάδ", "church": r"arriv|bride|groom|walk|enter",
           "couple": r"kiss|laugh|hug|ride|vespa|spin", "prep": r"laugh|talk|speak|joke|toast|cheer"}
MUSIC_DB, DUCK_DB = 0.0, -12.0
CROSSFADE = 2.0


def _part_of(s: Shot) -> str:
    if s.cat.kind == DRONE:
        return "drone"
    for key, rx in LABELS:
        if re.search(rx, s.cat.label_el):
            return key
    return "other"


@dataclass
class Slot:
    part: str
    start: float
    end: float
    shot: Shot | None = None
    src_in: float = 0.0
    live: str = ""        # "" | "film" | "live"


@dataclass
class WeddingHighlights:
    slots: list[Slot]
    songs: list[tuple[str, Media, float, float]]      # role, media, seq start, seq end
    title_at: float
    warnings: list[str] = field(default_factory=list)

    @property
    def end(self) -> float:
        return self.slots[-1].end if self.slots else 0.0


def _lengths(t: float, length: float, shot: float, beat: float, origin: float) -> list[float]:
    """Shot lengths for about `length` seconds from t: cuts every k beats of the song (k from the
    wanted shot length), the first one stretched to land on the song's beat grid."""
    k = max(1, round(shot / beat))
    step = k * beat
    nxt = origin + math.ceil((t + 0.6 * step - origin) / beat) * beat
    out = [nxt - t]
    while sum(out) + step <= length + step / 2:
        out.append(step)
    return out


def _snap(x: float, beat: float) -> float:
    return max(beat, round(x / beat) * beat)


def _pick(pool: list[Shot], n: int, used: set[str]) -> list[Shot]:
    """n shots spread over the part's time span, best in each stretch, no clip twice."""
    cands = sorted((s for s in pool if s.id not in used), key=lambda s: (s.start or datetime.min, s.id))
    if n <= 0 or not cands:
        return []
    out = []
    size = len(cands) / n
    for i in range(n):
        chunk = cands[int(i * size): max(int((i + 1) * size), int(i * size) + 1)]
        chunk = [s for s in chunk if s.id not in used] or [s for s in cands if s.id not in used]
        if not chunk:
            break
        best = max(chunk, key=lambda s: s.score)
        out.append(best)
        used.add(best.id)
    return sorted(out, key=lambda s: (s.start or datetime.min, s.id))


def _intercut(groups: list[list[Shot]]) -> list[Shot]:
    """Bride and groom getting ready alternate, each side in its own time order."""
    out, i = [], 0
    while any(groups):
        g = groups[i % len(groups)]
        if g:
            out.append(g.pop(0))
        i += 1
    return out


def build(p: Project, st: Structure, descs: dict[str, dict]) -> WeddingHighlights:
    allshots = [s for s in shots(p, st, descs) if not (s.issues & BAD)]
    pools: dict[str, list[Shot]] = {}
    for s in allshots:
        pools.setdefault(_part_of(s), []).append(s)
    drones = sorted(pools.get("drone", []), key=lambda s: (s.start or datetime.min))
    songs_needed = [r for r in ("intro", "story", "ceremony", "party")]
    tracks = {r: library.song("wedding", r) for r in songs_needed}
    warnings = [f"no {r} song in the library" for r, s in tracks.items() if s is None]
    analysed = {r: music.analyse(s) for r, s in tracks.items() if s}
    used: set[str] = set()
    slots: list[Slot] = []
    songs: list[tuple[str, Media, float, float]] = []
    t = 0.0
    song_start: dict[str, float] = {}

    def song_grid(role: str) -> tuple[float, float]:
        a = analysed.get(role) or {"beat": 0.5, "phase": 0.0}
        return a["beat"], song_start.get(role, t) + a["phase"]

    for part, role, length, shot_len in PARTS:
        if part == "baptism" and not pools.get("baptism"):
            continue
        if role not in song_start:
            song_start[role] = t
        beat, phase = song_grid(role)
        if part == "teaser":
            best = sorted((s for s in allshots if s.cat.kind != FLOW and _part_of(s) not in ("interviews", "other_day")
                           and s.duration > 2.5), key=lambda s: -s.score)
            picks, seen_parts = [], set()
            for s in best:                         # one strong moment from each part of the day
                pp = _part_of(s)
                if pp not in seen_parts or len(picks) >= 6:
                    picks.append(s)
                    seen_parts.add(pp)
                if len(picks) >= 9:
                    break
            for ln, s in zip(_lengths(t, length, shot_len, beat, phase), picks):
                slots.append(Slot(part, t, t + ln, s, s.window(ln)))
                used.add(s.id)
                t += ln
            continue
        if part in ("title", "final"):
            ln = _snap(length, beat)
            d = (max(drones, key=lambda s: drone_window(s, ln)[1]) if part == "title" and drones
                 else drones[-1] if drones else None)
            if d is not None:
                src, _ = drone_window(d, min(ln, d.duration - 0.2))
                slots.append(Slot(part, t, t + ln, d, src))
                used.add(d.id)
                t += ln
            continue
        pool = pools.get(part, [])
        if part == "place":
            pool = pool + [d for d in drones if d.id not in used][:1]
        if not pool:
            continue
        if part in DRONE_BEFORE:
            later = [d for d in drones if d.id not in used and d.start and pool[0].start and d.start <= max(s.start for s in pool if s.start)]
            if later:
                d = later[0]
                ln = _snap(2.8, beat)
                src, _ = drone_window(d, ln)
                slots.append(Slot("drone", t, t + ln, d, src))
                used.add(d.id)
                t += ln
        grid = _lengths(t, length, shot_len, beat, phase)
        n_live = FILM_PARTS.get(part, 0) + LIVE_PARTS.get(part, 0)
        regular = len(grid) - n_live
        if part == "prep":
            groom = [s for s in pool if "ΓΑΜΠΡ" in s.cat.label_el]
            bride = [s for s in pool if "ΝΥΦ" in s.cat.label_el]
            details = [s for s in pool if s not in groom and s not in bride]
            chosen = _pick(details, max(2, regular // 6), used)
            chosen += _intercut([_pick(groom, regular // 2, used), _pick(bride, regular - regular // 2 - len(chosen), used)])
        elif part == "party":
            chosen = _party(pool, regular, used)
        else:
            chosen = _pick(pool, regular, used)
        moments = _moments(pool, part, n_live, used)
        sequence = sorted(chosen + [m for m, _, _ in moments], key=lambda s: (s.start or datetime.min, s.id))
        if part == "prep":
            sequence = chosen[: max(2, regular // 6)] + _interleave(chosen[max(2, regular // 6):], [m for m, _, _ in moments])
        mom = {id(m): (tt, kind) for m, tt, kind in moments}
        cursor = t
        gi = 0
        for s in sequence:
            if id(s) in mom:
                tt, kind = mom[id(s)]
                ln = _snap(FILM_LEN if kind == "film" else LIVE_LEN, beat)
                slots.append(Slot(part, cursor, cursor + ln, s, s.window(ln, tt), kind))
                cursor += ln
            else:
                if gi >= len(grid):
                    break
                ln = grid[gi]
                gi += 1
                src = drone_window(s, ln)[0] if s.cat.kind == DRONE else s.window(ln)
                slots.append(Slot(part, cursor, cursor + ln, s, src))
                cursor += ln
        t = cursor

    # songs: each from its own start, crossfading into the next
    order = []
    for sl in slots:
        role = next(r for p_, r, *_ in PARTS if p_ == sl.part) if sl.part != "drone" else None
        if role and (not order or order[-1][0] != role):
            order.append([role, sl.start, sl.end])
        elif order:
            order[-1][2] = sl.end
    for k, (role, a, b) in enumerate(order):
        song = tracks.get(role)
        if not song:
            continue
        an = analysed[role]
        a0 = max(0.0, a - (CROSSFADE if k else 0.0))
        b0 = min(b + (CROSSFADE if k < len(order) - 1 else 0.0), a0 + an["duration"] - 0.1)
        songs.append((role, Media(str(song), an["duration"], has_video=False, audio_channels=2), a0, b0))
    title_at = next((sl.start for sl in slots if sl.part == "title"), 0.0)
    return WeddingHighlights(slots, songs, title_at, warnings)


def _interleave(a: list[Shot], b: list[Shot]) -> list[Shot]:
    if not b:
        return a
    out, step = [], max(1, len(a) // (len(b) + 1))
    bi = 0
    for i, s in enumerate(a):
        out.append(s)
        if bi < len(b) and (i + 1) % step == 0:
            out.append(b[bi])
            bi += 1
    return out + b[bi:]


def _party(pool: list[Shot], n: int, used: set[str]) -> list[Shot]:
    """The party is mostly long dance takes: several different moments of each, never one twice in a row."""
    out = _pick(pool, min(n, len(pool)), used)
    long_ = [s for s in pool if s.duration > 30]
    i = 0
    while len(out) < n and long_:
        out.append(long_[i % len(long_)])
        i += 1
    seq: list[Shot] = []
    for s in sorted(out, key=lambda s: (s.start or datetime.min)):
        if seq and seq[-1].id == s.id and len(set(x.id for x in out)) > 1:
            seq.insert(max(0, len(seq) - 1), s)
        else:
            seq.append(s)
    return seq


PHRASES = {"ceremony": ("crowning", "isaiah", "common_cup", "rings"), "baptism": ("immersion", "naming")}


def _phrase_hits(pool: list[Shot], part: str) -> list[tuple[float, Shot, float]]:
    """The ritual phrases in the ceremony masters' speech (Whisper), strongest first."""
    from hypershutter.core import transcribe
    out = []
    for s in pool:
        if s.cat.kind != FLOW or not s.media.audio_channels:
            continue
        try:
            segs = transcribe.transcribe(Path(s.media.path), "wedding" if part == "ceremony" else "baptism")
        except Exception:
            continue
        for rank, key in enumerate(PHRASES.get(part, ())):
            for seg in transcribe.find(segs, transcribe.MOMENTS[key]):
                if FLOOR_SKIP < seg.start < s.duration - 2:
                    out.append((10.0 - rank, s, max(FLOOR_SKIP, seg.start - 0.3)))
    return sorted(out, key=lambda x: (-x[0], x[2]))


def _moments(pool: list[Shot], part: str, n: int, used: set[str]) -> list[tuple[Shot, float, str]]:
    """Film scenes (and live-sound moments): first the ritual phrases found in the masters' speech,
    then the part's strongest notable moments; always with the moment's own sound."""
    if n <= 0:
        return []
    rx = re.compile(FILM_RX.get(part, r"."), re.I)
    hits = _phrase_hits(pool, part) if part in PHRASES else []
    for s in pool:
        if not s.media.audio_channels:
            continue
        for note in s.desc.get("notable") or []:
            t_ = float(note.get("t", 0))
            if t_ > FLOOR_SKIP and t_ < s.duration - 1 and rx.search(note.get("what", "")):
                hits.append((s.score + (1.0 if s.cat.kind == FLOW else 0), s, t_))
    hits.sort(key=lambda x: -x[0])
    out, taken = [], set()
    # one phrase moment per master; the same master may give two different phrases if nothing else exists
    kind = "live" if part in LIVE_PARTS else "film"
    for _, s, t_ in hits:
        if s.id in taken:
            continue
        out.append((s, t_, kind))
        taken.add(s.id)
        used.add(s.id)
        if len(out) >= n:
            break
    return out


def sequence(name: str, hl: WeddingHighlights) -> Sequence:
    """V1 picture; songs on A1/A2 and A3/A4 alternately (they crossfade); film and live sound on A5;
    projector and whooshes on A6; ambience on A7. Songs duck under film and live moments."""
    seq = Sequence(name, video=[[]], audio=[[] for _ in range(7)])
    for sl in hl.slots:
        if sl.shot is None:
            continue
        seq.video[0].append(Item(sl.shot.media, round(sl.start * FPS), round(sl.end * FPS), sl.src_in))
    ducks = [(round(sl.start * FPS), round(sl.end * FPS)) for sl in hl.slots if sl.live]
    for k, (role, media, a, b) in enumerate(hl.songs):
        pair = (0, 1) if k % 2 == 0 else (2, 3)
        start, end = round(a * FPS), round(b * FPS)
        cuts = sorted({start, end} | {x for d in ducks for x in d if start < x < end})
        for x, y in zip(cuts, cuts[1:]):
            inside = any(d0 <= x and y <= d1 for d0, d1 in ducks)
            for ch, tr in zip((1, 2), pair):
                seq.audio[tr].append(Item(media, x, y, (x - start) / FPS, channel=ch,
                                          gain_db=DUCK_DB if inside else MUSIC_DB,
                                          fade_in=round(CROSSFADE * FPS) if x == start and k else 0,
                                          fade_out=round(CROSSFADE * FPS) if y == end and k < len(hl.songs) - 1 else
                                          (round(1.2 * FPS) if y == end else 0)))
    projector = library.sfx("wedding", "projector")
    whoosh = library.sfx("wedding", "whoosh")
    ambience = library.sfx("wedding", "ambience")
    for sl in hl.slots:
        a, b = round(sl.start * FPS), round(sl.end * FPS)
        if sl.live and sl.shot.media.audio_channels:
            seq.audio[4].append(Item(sl.shot.media, a, b, sl.src_in, channel=1, fade_in=6, fade_out=10))
        if sl.live == "film" and projector:
            m = _sfx_media(projector[0])
            seq.audio[5].append(Item(m, a, min(b, a + round((m.duration - 0.2) * FPS)), 0.0, gain_db=-8.0, fade_in=4, fade_out=8))
            seq.markers.append(Marker("FILM – super 8 + ζωντανός ήχος στο A5", a))
    if whoosh and hl.title_at:
        m = _sfx_media(whoosh[0])
        a = max(0, round((hl.title_at - min(1.5, m.duration * 0.6)) * FPS))
        b = min(a + round((m.duration - 0.1) * FPS), round(hl.end * FPS))
        if not any(it.start < b and a < it.end for it in seq.audio[5]):
            seq.audio[5].append(Item(m, a, b, 0.0, gain_db=-6.0))
    if ambience:
        birds = next((x for x in ambience if re.search("bird|nature", x.name, re.I)), ambience[0])
        wind = next((x for x in ambience if re.search("wind", x.name, re.I)), ambience[0])
        m = _sfx_media(birds)
        end = min(round(hl.title_at * FPS) + 3 * FPS, round((m.duration - 0.2) * FPS))
        seq.audio[6].append(Item(m, 0, end, 0.0, gain_db=-14.0, fade_in=12, fade_out=25))
        final = next((sl for sl in hl.slots if sl.part == "final"), None)
        if final:
            mw = _sfx_media(wind)
            a = round(final.start * FPS)
            b = min(round(final.end * FPS), a + round((mw.duration - 0.2) * FPS))
            seq.audio[6].append(Item(mw, a, b, 0.0, gain_db=-12.0, fade_in=12, fade_out=20))
    if hl.title_at:
        seq.markers.insert(0, Marker("ΤΙΤΛΟΣ – τοποθεσία & ονόματα ζευγαριού (τα βάζεις εσύ)", round(hl.title_at * FPS)))
    for sl in hl.slots:
        if sl.shot and sl.shot.shaky:
            seq.markers.append(Marker(f"{sl.shot.clip.name}: needs Warp", round(sl.start * FPS)))
    return seq


def _sfx_media(path: Path) -> Media:
    from hypershutter.core.music import SR, load
    try:
        dur = len(load(path)) / SR
    except Exception:
        dur = 5.0
    return Media(str(path), dur, has_video=False, audio_channels=2)


# ---------------- ροή ----------------

CONDENSE = {"wedding": 0.30, "baptism": 0.45}     # share of each master the videographer keeps (his wedding ροή)
BED_DB = {"ceremony_camera": -8.0, "ceremony_mic": -20.0, "montage": -2.0, "under_speech": -18.0}
SPEECH_DB = {"camera": -3.0, "mic": 3.0, "interview": 0.0}


@dataclass
class FlowPlan:
    seq: Sequence
    warnings: list[str] = field(default_factory=list)

    @property
    def minutes(self) -> float:
        return round(self.seq.duration / FPS / 60, 1)


class _Flow:
    """Places pieces one after the other: V1 picture, A1 the speech (ceremony, interviews, dances),
    music beds on A2/A3 and A4/A5 (alternating so beds can crossfade), cutaways on V2."""

    def __init__(self, name: str, beds: list[Path]):
        self.seq = Sequence(name, video=[[], []], audio=[[] for _ in range(5)])
        self.t = 0                                   # sequence frames
        self.covers = [b for b in beds if re.search(r"piano|cello|violin|instrumental|cover", b.name, re.I)]
        self.songs = [b for b in beds if b not in self.covers]
        self.next = {"covers": 0, "songs": 0}
        self.bed_pair = 0
        self.speech: list[tuple[int, int]] = []      # spans where somebody speaks (beds duck)
        self.beds: list[tuple[int, int, str, float]] = []   # start, end, kind, gain
        self.used: set[str] = set()

    def put(self, s: Shot, src_in: float, length: float, sound: str = "", gain: float = 0.0, fade: int = 6) -> int:
        n = max(1, round(length * FPS))
        self.seq.video[0].append(Item(s.media, self.t, self.t + n, src_in))
        if sound and s.media.audio_channels:
            self.seq.audio[0].append(Item(s.media, self.t, self.t + n, src_in, channel=1, gain_db=gain,
                                          fade_in=fade, fade_out=fade))
            self.speech.append((self.t, self.t + n))
        self.used.add(s.id)
        self.t += n
        return self.t - n

    def montage(self, pool: list[Shot], seconds: float, shot: float = 2.4) -> None:
        n = max(1, round(seconds / shot))
        for s in _pick(pool, n, self.used):
            ln = min(shot, s.duration - 0.2)
            if ln < 0.8:
                continue
            src = drone_window(s, ln)[0] if s.cat.kind == DRONE else s.window(ln)
            self.put(s, src, ln)

    def bed(self, start: int, kind: str, gain: float, which: str = "songs") -> None:
        """Mark a stretch of the sequence (from start to now) that gets a music bed."""
        if self.t > start:
            self.beds.append((start, self.t, which, gain))

    def render_beds(self) -> None:
        for a, b, which, gain in self.beds:
            pool = self.covers if which == "covers" and self.covers else self.songs or self.covers
            if not pool:
                return
            t = a
            while t < b:
                song = pool[self.next[which] % len(pool)]
                self.next[which] += 1
                dur = len(music.load(song)) / music.SR
                end = min(b, t + round((dur - 0.2) * FPS))
                media = Media(str(song), dur, has_video=False, audio_channels=2)
                self._place_bed(media, t, end, gain)
                t = end
            continue

    def _place_bed(self, media: Media, a: int, b: int, gain: float) -> None:
        pair = (1, 2) if self.bed_pair % 2 == 0 else (3, 4)
        self.bed_pair += 1
        cuts = sorted({a, b} | {x for s in self.speech for x in s if a < x < b})
        for x, y in zip(cuts, cuts[1:]):
            under = any(s0 <= x and y <= s1 for s0, s1 in self.speech)
            g = min(gain, BED_DB["under_speech"]) if under and gain > BED_DB["under_speech"] else gain
            for ch, tr in zip((1, 2), pair):
                self.seq.audio[tr].append(Item(media, x, y, (x - a) / FPS, channel=ch, gain_db=g,
                                               fade_in=round(2 * FPS) if x == a else 0,
                                               fade_out=round(2 * FPS) if y == b else 0))


def _mic_for(p: Project, master: Shot) -> tuple[Media, float] | None:
    """The lapel-mic recording that covers this master, and where the master starts inside it."""
    from hypershutter.core.edit import media_of
    if master.start is None:
        return None
    for c in p.clips.values():
        dev = p.devices.get(c.device)
        t0 = p.corrected(c)
        if c.kind == "audio" and dev and dev.kind == "recorder" and t0:
            off = (master.start - t0).total_seconds()
            if 0 <= off and off + master.duration <= c.duration + 1:
                return media_of(p, c), off
    return None


def build_flow(name: str, p: Project, st: Structure, descs: dict[str, dict]) -> FlowPlan:
    from hypershutter.core import transcribe
    from hypershutter.core.edit import _cutaways, ceremony_groups
    allshots = shots(p, st, descs)
    pools: dict[str, list[Shot]] = {}
    for s in allshots:
        pools.setdefault(_part_of(s), []).append(s)
    drones = sorted(pools.get("drone", []), key=lambda s: s.start or datetime.min)
    interviews = sorted(pools.get("interviews", []), key=lambda s: s.start or datetime.min)
    q = max(1, len(interviews) // 4)
    iv_parts = [interviews[: 2 * q], interviews[2 * q: 3 * q], interviews[3 * q:]]
    f = _Flow(name, library.beds("wedding"))
    warnings: list[str] = []

    def interview(s: Shot) -> None:
        ln = min(s.duration - FLOOR_SKIP - 0.3, 30.0)
        if ln > 2:
            f.put(s, FLOOR_SKIP, ln, sound="interview", gain=SPEECH_DB["interview"], fade=8)

    # 1. getting ready intercut with interviews, under music
    a = f.t
    prep = sorted(pools.get("prep", []), key=lambda s: s.start or datetime.min)
    blocks = [prep[i:i + 4] for i in range(0, min(len(prep), 40), 4)]
    for k, block in enumerate(blocks):
        f.montage(block, 2.4 * len(block), 2.4)
        if k < len(iv_parts[0]):
            interview(iv_parts[0][k])
    for s in iv_parts[0][len(blocks):]:
        interview(s)
    f.bed(a, "montage", BED_DB["montage"])
    f.seq.markers.append(Marker("ΕΤΟΙΜΑΣΙΑ & ΣΥΝΕΝΤΕΥΞΕΙΣ", 0))

    # 2. the place, church & arrival
    a = f.t
    if drones:
        d = drones[0]
        f.put(d, drone_window(d, 6.0)[0], 6.0)
    f.montage(pools.get("place", []), 6.0, 2.0)
    f.montage(pools.get("church", []), 75.0, 2.6)
    f.bed(a, "montage", BED_DB["montage"])

    # 3. ceremonies: the ritual (from the speech), cutaways over the joins and every ~45 s
    for cer_name, cats in ceremony_groups(st):
        keys = {c.key for c in cats}
        masters = sorted((s for s in allshots if s.cat.key in keys and s.cat.kind == FLOW), key=lambda s: s.start or datetime.min)
        broll = [s for s in allshots if s.cat.key in keys and s.cat.kind == BROLL]
        baptism = cer_name.startswith("ΒΑΦΤ")
        if baptism:
            a = f.t
            if len(drones) > 1:
                d = drones[len(drones) // 2]
                f.put(d, drone_window(d, 5.0)[0], 5.0)
            f.montage([s for s in pools.get("baptism", []) if s.cat.kind not in (FLOW, BROLL)], 30.0, 2.2)
            f.bed(a, "montage", BED_DB["montage"])
        start = f.t
        f.seq.markers.append(Marker(f"{cer_name} — Impact Dissolve", f.t))
        placed = []
        any_mic = False
        for m in masters:
            try:
                segs = transcribe.transcribe(Path(m.media.path), "baptism" if baptism else "wedding")
                ranges = transcribe.condense(segs, CONDENSE["baptism" if baptism else "wedding"], FLOOR_SKIP,
                                             m.duration, boost=m.notable())
            except Exception as e:                       # no speech model: keep the whole master
                warnings.append(f"{m.clip.name}: no transcript ({e}); kept whole")
                ranges = [(FLOOR_SKIP, m.duration - 0.5)]
            mic = _mic_for(p, m)
            for x, y in ranges:
                y = min(y, m.duration - 0.2)
                if y - x < 2:
                    continue
                s0 = f.put(m, x, y - x)
                n = f.t - s0
                if mic:
                    media, off = mic
                    f.seq.audio[0].append(Item(media, s0, s0 + n, off + x, channel=1, gain_db=SPEECH_DB["mic"],
                                               fade_in=4, fade_out=4))
                    any_mic = True
                elif m.media.audio_channels:
                    f.seq.audio[0].append(Item(m.media, s0, s0 + n, x, channel=1, gain_db=SPEECH_DB["camera"],
                                               fade_in=4, fade_out=4))
                placed.append((m, s0, x, y))
        _cutaways(f.seq, placed, broll, f.used, [])
        f.bed(start, "ceremony", BED_DB["ceremony_mic" if any_mic else "ceremony_camera"], "covers")
        if not baptism:
            a = f.t                                      # exit & wishes, then the couple shoot
            f.montage(pools.get("exit", []), 30.0, 2.0)
            f.montage(pools.get("couple", []), 30.0, 2.4)
            f.bed(a, "montage", BED_DB["montage"])
    if not ceremony_groups(st):
        warnings.append("no ceremony masters found")

    # 4. wishes and the reception
    a = f.t
    for s in iv_parts[1]:
        interview(s)
    f.montage(pools.get("reception", []), 60.0, 2.2)
    f.bed(a, "montage", BED_DB["montage"])

    # 5. dances in full with their own sound, the last interviews between them, a closing drone
    dances = sorted((s for s in pools.get("party", []) if s.duration > 20), key=lambda s: s.start or datetime.min)
    if dances:
        f.seq.markers.append(Marker("ΧΟΡΟΙ – ολόκληροι, ήχος από την κάμερα (Impact Dissolve σε κάθε αλλαγή)", f.t))
    gaps = max(1, len(dances) // (len(iv_parts[2]) + 1)) if iv_parts[2] else 0
    k_iv = 0
    for k, d in enumerate(dances):
        if k:
            f.seq.markers.append(Marker("Impact Dissolve", f.t))
        f.put(d, 2.0, d.duration - 4.0, sound="camera", gain=0.0, fade=25 if k == 0 else 6)
        if gaps and (k + 1) % gaps == 0 and k_iv < len(iv_parts[2]):
            interview(iv_parts[2][k_iv])
            k_iv += 1
    if drones:
        d = drones[-1]
        f.put(d, drone_window(d, 6.0)[0], 6.0)
    f.render_beds()
    for tr in f.seq.audio:
        tr.sort(key=lambda i: i.start)
    return FlowPlan(f.seq, warnings)
