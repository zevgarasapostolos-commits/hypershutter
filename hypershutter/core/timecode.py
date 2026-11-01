"""Capture time parsing, best source first.

1. Sony XML sidecar  <CreationDate value="2026-10-11T13:16:14+03:00"/>  (local, with zone)
2. DJI drone name    DJI_20261011163207_0033_D                          (local)
3. DJI recorder name DJI_02_20261004_120804                              (local)
4. DJI .SRT          first timestamp line                                (local)
5. container creation_time                                               (UTC)
6. file mtime minus duration                                             (local, last resort)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Athens")

DJI_VIDEO_RE = re.compile(r"^DJI_(\d{14})_\d{4}(?:_[A-Z])?$")
DJI_REC_RE = re.compile(r"^DJI_\d{2}_(\d{8})_(\d{6})$")
SRT_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
SONY_DATE_RE = re.compile(r'<CreationDate\s+value="([^"]+)"')
SONY_DEVICE_RE = re.compile(r'<Device\s+manufacturer="([^"]*)"\s+modelName="([^"]*)"(?:\s+serialNo="([^"]*)")?')


def parse_dji_video_name(stem: str) -> datetime | None:
    m = DJI_VIDEO_RE.match(stem)
    return datetime.strptime(m.group(1), "%Y%m%d%H%M%S") if m else None


def parse_recorder_name(stem: str) -> datetime | None:
    m = DJI_REC_RE.match(stem)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S") if m else None


def parse_srt_start(text: str) -> datetime | None:
    m = SRT_TIME_RE.search(text[:4000])
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}") if m else None


def parse_sony_xml(text: str) -> dict:
    """Returns {'local': naive local datetime, 'model': ..., 'serial': ...} (keys only when found)."""
    out: dict = {}
    m = SONY_DATE_RE.search(text)
    if m:
        try:
            aware = datetime.fromisoformat(m.group(1))
            # The reading is the camera's displayed local time; keep it naive.
            out["local"] = aware.replace(tzinfo=None)
        except ValueError:
            pass
    d = SONY_DEVICE_RE.search(text)
    if d:
        out["model"] = f"{d.group(1)} {d.group(2)}".strip()
        out["serial"] = d.group(3) or ""
    return out


def parse_creation_time(value: str | None) -> datetime | None:
    """ffprobe creation_time, e.g. '2026-10-11T02:59:15.000000Z' -> naive UTC reading."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if dt.year < 2000:          # unset clocks write 1904/1970
        return None
    return dt


def utc_to_local(naive_utc: datetime) -> tuple[datetime, float]:
    """Naive UTC -> naive Greek local time, plus the zone offset used (seconds)."""
    local = naive_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return local.replace(tzinfo=None), local.utcoffset().total_seconds()


def capture_reading(stem: str, probe: dict, sidecar_texts: dict[str, str], mtime: float,
                    duration: float) -> tuple[datetime | None, str, datetime | None, float]:
    """Best capture time for one clip.

    Returns (reading, source, nominal_local, tz_offset_seconds). `reading` is what the
    device wrote; `nominal_local` is it converted to local time (before drift correction).
    """
    for name, text in sidecar_texts.items():
        if name.lower().endswith(".xml"):
            local = parse_sony_xml(text).get("local")
            if local:
                return local, "sony_xml", local, 0.0
    t = parse_dji_video_name(stem)
    if t:
        return t, "dji_name", t, 0.0
    t = parse_recorder_name(stem)
    if t:
        return t, "rec_name", t, 0.0
    for name, text in sidecar_texts.items():
        if name.lower().endswith(".srt"):
            t = parse_srt_start(text)
            if t:
                return t, "dji_srt", t, 0.0
    t = parse_creation_time(probe.get("creation_time"))
    if t:
        local, tz = utc_to_local(t)
        return t, "creation_time", local, tz
    if mtime:
        end = datetime.fromtimestamp(mtime, LOCAL_TZ).replace(tzinfo=None)
        start = end - timedelta(seconds=duration or 0)
        return start, "mtime", start, 0.0
    return None, "", None, 0.0


def read_text(path: Path, limit: int = 65536) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", errors="ignore")
    except OSError:
        return ""
