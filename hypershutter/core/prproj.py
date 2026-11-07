"""Read a Premiere Pro project (.prproj) to learn from the videographer's own edit.

A .prproj is gzip-compressed XML: a flat list of objects that point at each other through
ObjectID/ObjectRef and ObjectUID/ObjectURef. From each sequence we extract every track item:
where it sits on the timeline, which file and which part of it, speed, effects, and the names
of transitions. Times are Premiere ticks, 254016000000 per second. Read-only, on a copy.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

TICKS = 254016000000


def _db(v: float) -> float:
    """Premiere's internal clip volume (1.0 = +15 dB) to dB."""
    import math
    return 20 * math.log10(max(v, 1e-6)) + 15


@dataclass
class TrackItem:
    track: str            # V1, V2, A1 …
    start: float          # seconds on the sequence
    end: float
    name: str
    path: str = ""        # media file ("" for graphics, nested sequences, generated items)
    src_in: float = 0.0   # seconds inside the source
    src_out: float = 0.0
    speed: float = 1.0
    kind: str = "clip"    # clip | nested | graphic | other
    nested: str = ""      # nested sequence name
    effects: list[str] = field(default_factory=list)
    gain_db: list[float] = field(default_factory=list)   # audio: clip volume levels (constant or keyframes), dB

    @property
    def level_db(self) -> float | None:
        """Typical clip volume: the median of its levels (0 dB = unchanged)."""
        if not self.gain_db:
            return None
        g = sorted(self.gain_db)
        return g[len(g) // 2]

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class SequenceInfo:
    name: str
    items: list[TrackItem]
    markers: list[tuple[float, str]] = field(default_factory=list)
    transitions: list[tuple[str, float, str]] = field(default_factory=list)   # track, at, name

    @property
    def duration(self) -> float:
        return max((i.end for i in self.items), default=0.0)

    def track(self, name: str) -> list[TrackItem]:
        return sorted((i for i in self.items if i.track == name), key=lambda i: i.start)


class Project:
    def __init__(self, path: Path):
        raw = Path(path).read_bytes()
        data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        self.root = ET.fromstring(data)
        self.by_id: dict[str, ET.Element] = {}
        self.by_uid: dict[str, ET.Element] = {}
        for el in self.root:
            if el.get("ObjectID"):
                self.by_id[el.get("ObjectID")] = el
            if el.get("ObjectUID"):
                self.by_uid[el.get("ObjectUID")] = el

    def ref(self, el: ET.Element | None) -> ET.Element | None:
        if el is None:
            return None
        if el.get("ObjectRef"):
            return self.by_id.get(el.get("ObjectRef"))
        if el.get("ObjectURef"):
            return self.by_uid.get(el.get("ObjectURef"))
        return None

    def sequences(self) -> list[ET.Element]:
        return [el for el in self.root if el.tag == "Sequence"]

    def sequence_by_uid(self, uid: str) -> ET.Element | None:
        return self.by_uid.get(uid)

    # -------- media of a clip --------

    def _media_path(self, source: ET.Element | None) -> tuple[str, str, str]:
        """(kind, path or nested name, display name) of a clip's source."""
        if source is None:
            return "other", "", ""
        if source.tag in ("VideoSequenceSource", "AudioSequenceSource"):
            seq = self.ref(source.find("SequenceSource/Sequence"))
            name = seq.findtext("Name") if seq is not None else ""
            return "nested", name or "", name or ""
        media = self.ref(source.find("MediaSource/Media"))
        if media is None:
            return "other", "", ""
        path = media.findtext("ActualMediaFilePath") or media.findtext("FilePath") or ""
        title = media.findtext("Title") or Path(path).name
        if not path or path.lower().endswith((".aegraphic", ".mogrt")) or media.findtext("IsGenerated") == "true":
            return "graphic", path, title
        return "clip", path, title

    def _effects(self, track_item: ET.Element) -> list[str]:
        names = []
        chain = self.ref(track_item.find("ClipTrackItem/ComponentOwner/Components"))
        if chain is None:
            return names
        for comp in chain.iter("Component"):
            c = self.ref(comp)
            if c is not None:
                n = c.findtext("Component/DisplayName") or c.findtext("DisplayName") or c.findtext("Component/MatchName") or ""
                if n:
                    names.append(n)
        return names

    # -------- sequences --------

    def read(self, seq: ET.Element) -> SequenceInfo:
        info = SequenceInfo(seq.findtext("Name") or "", [])
        for tg in seq.findall("TrackGroups/TrackGroup"):
            group = self.ref(tg.find("Second"))
            if group is None or group.tag not in ("VideoTrackGroup", "AudioTrackGroup"):
                continue
            prefix = "V" if group.tag == "VideoTrackGroup" else "A"
            for n, t in enumerate(group.findall("TrackGroup/Tracks/Track"), start=1):
                track = self.ref(t)
                if track is None:
                    continue
                for ti in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
                    item = self.ref(ti)
                    if item is not None:
                        self._add_item(info, f"{prefix}{n}", item)
                for ti in track.findall("ClipTrack/TransitionItems/TrackItems/TrackItem"):
                    tr = self.ref(ti)
                    if tr is not None:
                        start = int(tr.findtext("TransitionTrackItem/TrackItem/Start") or 0) / TICKS
                        comp = self.ref(tr.find("TransitionTrackItem/Component"))
                        nm = ""
                        if comp is not None:
                            nm = comp.findtext("Component/DisplayName") or comp.findtext("DisplayName") or comp.tag
                        info.transitions.append((f"{prefix}{n}", start, nm))
        info.markers = self._markers(seq)
        return info

    def _add_item(self, info: SequenceInfo, track: str, item: ET.Element) -> None:
        start = int(item.findtext("ClipTrackItem/TrackItem/Start") or 0) / TICKS
        end = int(item.findtext("ClipTrackItem/TrackItem/End") or 0) / TICKS
        sub = self.ref(item.find("ClipTrackItem/SubClip"))
        clip = self.ref(sub.find("Clip")) if sub is not None else None
        name = (sub.findtext("Name") if sub is not None else "") or ""
        src_in = src_out = 0.0
        speed = 1.0
        kind, path, title = "other", "", name
        if clip is not None:
            src_in = int(clip.findtext("Clip/InPoint") or 0) / TICKS
            src_out = int(clip.findtext("Clip/OutPoint") or 0) / TICKS
            speed = float(clip.findtext("Clip/PlaybackSpeed") or 1.0)
            kind, path, title = self._media_path(self.ref(clip.find("Clip/Source")))
        info.items.append(TrackItem(track, start, end, name or title, path if kind != "nested" else "", src_in, src_out,
                                    speed, kind, path if kind == "nested" else "", self._effects(item),
                                    self._gain(item) if track.startswith("A") else []))

    def _gain(self, item: ET.Element) -> list[float]:
        chain = self.ref(item.find("ClipTrackItem/ComponentOwner/Components"))
        if chain is None:
            return []
        for comp in chain.iter("Component"):
            c = self.ref(comp)
            if c is None or "Volume" not in (c.findtext("FilterMatchName") or ""):
                continue
            for p in c.iter("Param"):
                par = self.ref(p)
                if par is None or par.find("StartKeyframe") is None:
                    continue
                keys = par.findtext("Keyframes") or ""
                vals = [float(k.split(",")[1]) for k in keys.split(";") if k.count(",") >= 1] if keys else []
                if not vals:
                    vals = [float((par.findtext("CurrentValue") or par.findtext("StartKeyframe").split(",")[1]))]
                return [round(_db(v), 1) for v in vals]
        return []

    def _markers(self, seq: ET.Element) -> list[tuple[float, str]]:
        out = []
        node = seq.find("Node/Properties")
        for el in seq.iter():
            if el.tag.endswith("Markers") and (el.get("ObjectRef") or el.get("ObjectURef")):
                mk = self.ref(el)
                if mk is None:
                    continue
                for m in mk.iter("Marker"):
                    mm = self.ref(m) if (m.get("ObjectRef") or m.get("ObjectURef")) else m
                    if mm is None:
                        continue
                    t = mm.findtext(".//Start")
                    nm = mm.findtext(".//Name") or ""
                    if t:
                        out.append((int(t) / TICKS, nm))
        _ = node
        return sorted(out)


def load(path: Path) -> tuple[Project, dict[str, SequenceInfo]]:
    proj = Project(path)
    return proj, {s.findtext("Name") or s.get("ObjectUID"): proj.read(s) for s in proj.sequences()}
