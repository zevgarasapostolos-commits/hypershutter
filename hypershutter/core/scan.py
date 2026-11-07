"""Walk an event folder (read-only): clips, sidecars, ffprobe, devices, capture times."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Callable

from hypershutter.core import config, store, timecode
from hypershutter.core.media import AUDIO_EXT, SIDECAR_EXT, VIDEO_EXT, Clip, Device
from hypershutter.core.project import Project

SKIP_DIR_PREFIXES = ("adobe premiere pro", "premiere composer files", "00 contact sheets", ".hypershutter")
MUSIC_DIRS = {"music", "mousiki", "μουσικη", "μουσικες", "songs"}
GENERATED_DIRS = {"proxies", "exports"}          # HyperShutter's own outputs, never footage to sort
SONY_SIDECAR_RE = re.compile(r"^(.+?)M\d{2}$")      # C6501M01 -> C6501
SERIES_RE = re.compile(r"^(.*?)(\d+)$")
SERIES_GAP = 500           # numbering gap that separates two cameras sharing a prefix
CONTINUATION_GAP = 50      # a card/day change continues the numbering closely


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFD", name.casefold())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").strip()


def _skip_dir(name: str) -> bool:
    n = _norm(name)
    return name.startswith(".") or n.startswith(SKIP_DIR_PREFIXES) or n in MUSIC_DIRS or n in GENERATED_DIRS


def discover(root: Path) -> tuple[list[Clip], list[str], list[str]]:
    """Return (clips without probe, ignored rel paths, orphan sidecar rel paths)."""
    clips: list[Clip] = []
    ignored: list[str] = []
    sidecars_by_dir: dict[str, list[str]] = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        for d in list(dirnames):
            if _skip_dir(d):
                dirnames.remove(d)
                ignored.append(os.path.join(rel_dir, d) + "/")
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.startswith("._") or fn.startswith("."):
                continue
            rel = os.path.join(rel_dir, fn)
            ext = os.path.splitext(fn)[1].lower()
            if not rel_dir:                       # event root: project files, XMLs, previews
                ignored.append(rel)
                continue
            if ext in VIDEO_EXT or ext in AUDIO_EXT:
                st = os.stat(os.path.join(dirpath, fn))
                clips.append(Clip(id=os.path.splitext(fn)[0], rel=rel,
                                  kind="video" if ext in VIDEO_EXT else "audio",
                                  size=st.st_size, mtime=st.st_mtime))
            elif ext in SIDECAR_EXT:
                sidecars_by_dir[rel_dir].append(fn)
            else:
                ignored.append(rel)

    # Unique ids: identical stems in two folders (two drones, two cards) get a suffix.
    seen: Counter = Counter()
    for c in sorted(clips, key=lambda c: c.rel):
        seen[c.id] += 1
        if seen[c.id] > 1:
            c.id = f"{c.id}~{seen[c.id]}"

    orphans: list[str] = []
    by_dir_stem = {(os.path.dirname(c.rel), os.path.splitext(c.name)[0]): c for c in clips}
    for rel_dir, names in sidecars_by_dir.items():
        for fn in names:
            stem = os.path.splitext(fn)[0]
            m = SONY_SIDECAR_RE.match(stem)
            owner = by_dir_stem.get((rel_dir, stem)) or (m and by_dir_stem.get((rel_dir, m.group(1))))
            if owner:
                owner.sidecars.append(os.path.join(rel_dir, fn))
            else:
                orphans.append(os.path.join(rel_dir, fn))
    return clips, ignored, orphans


def _fps(rate: str | None) -> float:
    try:
        num, den = (rate or "0/1").split("/")
        return round(float(num) / float(den), 3) if float(den) else 0.0
    except ValueError:
        return 0.0


def probe_file(path: Path) -> dict:
    """Compact ffprobe summary; {'error': ...} when the file cannot be read."""
    ffprobe = config.find_tool("ffprobe") or "ffprobe"
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timeout"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"error": (r.stderr.strip().splitlines() or ["unreadable"])[-1][:200]}
    data = json.loads(r.stdout)
    fmt = data.get("format", {})
    out: dict = {"duration": float(fmt.get("duration") or 0.0), "nb_streams": len(data.get("streams", []))}
    ctime = (fmt.get("tags") or {}).get("creation_time")
    for s in data.get("streams", []):
        tags = s.get("tags") or {}
        ctime = ctime or tags.get("creation_time")
        disp = s.get("disposition") or {}
        # DJI files carry an extra mjpeg thumbnail stream after the real video.
        if (s.get("codec_type") == "video" and "vcodec" not in out and not disp.get("attached_pic")
                and s.get("codec_name") not in ("mjpeg", "png")):
            out.update(vcodec=s.get("codec_name"), width=s.get("width"), height=s.get("height"),
                       fps=_fps(s.get("avg_frame_rate") or s.get("r_frame_rate")), pix_fmt=s.get("pix_fmt"),
                       profile=s.get("profile"), bit_depth=int(s.get("bits_per_raw_sample") or 0) or None)
            for sd in s.get("side_data_list") or []:
                if "rotation" in sd:
                    out["rotation"] = int(sd["rotation"])
        elif s.get("codec_type") == "audio" and "acodec" not in out:
            out.update(acodec=s.get("codec_name"), channels=s.get("channels"),
                       sample_rate=int(s.get("sample_rate") or 0))
    out["creation_time"] = ctime
    return out


def probe_all(root: Path, clips: list[Clip], workers: int = 6,
              progress: Callable[[int, int], None] | None = None) -> None:
    db = store.connect()
    todo = []
    for c in clips:
        cached = store.get_probe(db, store.file_key(c.name, c.size, c.mtime))
        if cached is not None:
            c.probe = cached
        else:
            todo.append(c)
    done = len(clips) - len(todo)
    if progress:
        progress(done, len(clips))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, pr in zip(todo, ex.map(lambda c: probe_file(root / c.rel), todo)):
            c.probe = pr
            if "error" not in pr:
                store.put_probe(db, store.file_key(c.name, c.size, c.mtime), pr)
            done += 1
            if progress:
                progress(done, len(clips))
    db.commit()
    db.close()


def _series(stem: str) -> tuple[str, int | None, int]:
    m = SERIES_RE.match(stem.split("~")[0])
    return (m.group(1), int(m.group(2)), len(m.group(2))) if m else (stem, None, 0)


def _pattern(ids: list[str]) -> str:
    nums = sorted(n for _, n, _ in map(_series, ids) if n is not None)
    if not nums:
        return ""
    prefix, _, width = _series(ids[0])
    lo, hi = f"{nums[0]:0{width}d}", f"{nums[-1]:0{width}d}"
    a, b = f"{prefix}{lo[:-2]}xx", f"{prefix}{hi[:-2]}xx"
    return a if a == b else f"{a}–{b}"


def assign_devices(clips: list[Clip], sony_meta: dict[str, dict]) -> dict[str, Device]:
    """Group clips into recording devices by file pattern, numbering and Sony serials."""
    groups: dict[str, list[Clip]] = defaultdict(list)
    kinds: dict[str, str] = {}
    cams: list[list[Clip]] = []
    by_serial: dict[str, list[Clip]] = defaultdict(list)
    by_prefix: dict[tuple, list[Clip]] = defaultdict(list)
    for c in clips:
        stem = c.id.split("~")[0]
        if c.kind == "video" and stem.upper().startswith("DJI_"):
            groups["DJI"].append(c); kinds["DJI"] = "drone"
        elif c.kind == "audio":
            prefix = "REC" if timecode.DJI_REC_RE.match(stem) else re.sub(r"[\d_\-]+$", "", stem).upper() or "REC"
            key = prefix if prefix == "REC" else f"REC-{prefix}"
            groups[key].append(c); kinds[key] = "recorder"
        elif sony_meta.get(c.id, {}).get("serial"):
            by_serial[sony_meta[c.id]["serial"]].append(c)
        else:
            prefix, _, width = _series(stem)
            by_prefix[(prefix.upper(), width)].append(c)

    # Number clusters per prefix: a big gap in numbering = a different camera.
    clusters: list[list[Clip]] = []
    for _, cs in by_prefix.items():
        cs.sort(key=lambda c: (_series(c.id)[1] or 0, c.id))
        cur = [cs[0]]
        for c in cs[1:]:
            if (_series(c.id)[1] or 0) - (_series(cur[-1].id)[1] or 0) > SERIES_GAP:
                clusters.append(cur); cur = []
            cur.append(c)
        clusters.append(cur)
    # Clusters without XML join a serial-identified camera whose numbering they continue.
    for serial, cs in by_serial.items():
        nums = [_series(c.id)[1] or 0 for c in cs]
        lo, hi = min(nums) - CONTINUATION_GAP, max(nums) + CONTINUATION_GAP
        for cl in list(clusters):
            if any(lo <= (_series(c.id)[1] or 0) <= hi for c in cl):
                cs.extend(cl); clusters.remove(cl)
        cams.append(cs)
    cams.extend(clusters)

    devices: dict[str, Device] = {}
    for i, cs in enumerate(sorted(cams, key=lambda cs: -len(cs))):
        dev_id = chr(ord("A") + i) if i < 26 else f"CAM{i + 1}"
        groups[dev_id] = cs; kinds[dev_id] = "camera"
    for dev_id, cs in groups.items():
        cs.sort(key=lambda c: c.id)
        for c in cs:
            c.device = dev_id
        model = Counter(sony_meta.get(c.id, {}).get("model", "") for c in cs).most_common(1)[0][0]
        source = Counter(c.source for c in cs).most_common(1)[0][0]
        pattern = "DJI" if dev_id == "DJI" else (_pattern([c.id for c in cs]) if kinds[dev_id] == "camera" else
                                                 re.sub(r"\d{8}_\d{6}$", "…", cs[0].id))
        devices[dev_id] = Device(id=dev_id, kind=kinds[dev_id], clips=[c.id for c in cs], pattern=pattern,
                                 model=model, source=source)
    return devices


def scan(root: Path, workers: int = 6, progress: Callable[[str, int, int], None] | None = None) -> Project:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    clips, ignored, orphans = discover(root)
    probe_all(root, clips, workers, (lambda d, t: progress("probe", d, t)) if progress else None)

    sony_meta: dict[str, dict] = {}
    tz_by_clip: dict[str, float] = {}
    for c in clips:
        texts = {s: timecode.read_text(root / s) for s in c.sidecars if s.lower().endswith((".xml", ".srt"))}
        for name, text in texts.items():
            if name.lower().endswith(".xml"):
                sony_meta[c.id] = timecode.parse_sony_xml(text)
        reading, source, nominal, tz = timecode.capture_reading(
            c.id.split("~")[0], c.probe, texts, c.mtime, c.duration)
        c.reading = reading.isoformat() if reading else None
        c.nominal = nominal.isoformat() if nominal else None
        c.source = source
        tz_by_clip[c.id] = tz

    devices = assign_devices(clips, sony_meta)
    for d in devices.values():
        # Only a UTC-writing device has a zone offset between its reading and local time.
        tzs = [tz_by_clip[c] for c in d.clips if tz_by_clip.get(c)] if d.source == "creation_time" else []
        d.tz_offset = median(tzs) if tzs else 0.0

    p = Project(root=str(root), name=root.name, ignored=ignored, orphans=orphans,
                scanned_at=datetime.now().isoformat(timespec="seconds"))
    p.clips = {c.id: c for c in clips}
    p.devices = devices
    return p
