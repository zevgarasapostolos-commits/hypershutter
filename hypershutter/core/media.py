"""Data model shared by every pipeline stage.

Times: `reading` is the device clock exactly as recorded (naive), `nominal` is that
reading converted to Greek local time by its source rule (UTC -> Europe/Athens, or
already local), and `corrected = nominal + device.drift`. The user talks about
offsets relative to the raw reading ("camera A is +14:00"), see Device.raw_offset.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".mts", ".m2ts", ".avi", ".mkv", ".insv"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".aif", ".aiff"}
SIDECAR_EXT = {".xml", ".srt", ".lrf", ".thm", ".xmp", ".bim", ".cpi"}


@dataclass
class Clip:
    id: str                      # file stem, unique within the project ("C4255")
    rel: str                     # path relative to the event root
    kind: str                    # "video" | "audio"
    size: int
    mtime: float
    sidecars: list[str] = field(default_factory=list)
    probe: dict = field(default_factory=dict)
    device: str = ""
    reading: str | None = None   # ISO, naive: what the device clock wrote
    source: str = ""             # sony_xml | dji_name | rec_name | dji_srt | creation_time | mtime
    nominal: str | None = None   # ISO, naive local time before drift correction
    flags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return float(self.probe.get("duration") or 0.0)

    @property
    def has_audio(self) -> bool:
        return bool(self.probe.get("acodec"))

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    def nominal_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.nominal) if self.nominal else None


@dataclass
class Device:
    id: str                      # "A", "B", "DJI", "REC"
    kind: str                    # camera | drone | recorder
    clips: list[str] = field(default_factory=list)
    pattern: str = ""            # "C41xx–C43xx"
    model: str = ""              # from Sony XML when present
    source: str = ""             # dominant time source
    drift: float = 0.0           # seconds added to nominal time
    drift_status: str = "default"   # default | auto | manual | anchor | unresolved
    confidence: float = 0.0
    evidence: list[dict] = field(default_factory=list)
    tz_offset: float = 0.0       # seconds between raw UTC reading and local (UTC sources only)

    @property
    def raw_offset(self) -> float:
        """Offset vs the raw clock reading, as the user's index states it (e.g. +14:00)."""
        return self.tz_offset + self.drift


def corrected(clip: Clip, devices: dict[str, Device]) -> datetime | None:
    nom = clip.nominal_dt()
    if nom is None:
        return None
    dev = devices.get(clip.device)
    return nom + timedelta(seconds=dev.drift if dev else 0.0)


def fmt_offset(seconds: float) -> str:
    sign = "-" if seconds < 0 else "+"
    s = int(round(abs(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{sign}{h:02d}:{m:02d}" + (f":{sec:02d}" if sec else "")


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def to_dict(obj) -> dict:
    return asdict(obj)
