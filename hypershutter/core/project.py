"""Project state: the clips and devices of one event, persisted in SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from hypershutter.core import store
from hypershutter.core.media import Clip, Device, corrected


@dataclass
class Project:
    root: str
    name: str
    clips: dict[str, Clip] = field(default_factory=dict)
    devices: dict[str, Device] = field(default_factory=dict)
    ignored: list[str] = field(default_factory=list)     # deliverables, music, non-media
    orphans: list[str] = field(default_factory=list)     # sidecars with no clip
    scanned_at: str = ""
    synced_at: str = ""

    def to_json(self) -> dict:
        from dataclasses import asdict
        return {
            "root": self.root, "name": self.name, "scanned_at": self.scanned_at, "synced_at": self.synced_at,
            "ignored": self.ignored, "orphans": self.orphans,
            "clips": [asdict(c) for c in self.clips.values()],
            "devices": [asdict(d) for d in self.devices.values()],
        }

    @classmethod
    def from_json(cls, d: dict) -> "Project":
        p = cls(root=d["root"], name=d["name"], ignored=d.get("ignored", []), orphans=d.get("orphans", []),
                scanned_at=d.get("scanned_at", ""), synced_at=d.get("synced_at", ""))
        p.clips = {c["id"]: Clip(**c) for c in d.get("clips", [])}
        p.devices = {x["id"]: Device(**x) for x in d.get("devices", [])}
        return p

    def save(self) -> None:
        store.save_project(Path(self.root), self.to_json())

    @classmethod
    def load(cls, root: Path) -> "Project | None":
        d = store.load_project(root)
        if d is None:
            return None
        p = cls.from_json(d)
        p.root = str(root)        # the drive may have re-mounted under another name
        return p

    def corrected(self, clip: Clip) -> datetime | None:
        return corrected(clip, self.devices)

    def timeline(self) -> list[tuple[datetime, Clip]]:
        rows = [(self.corrected(c), c) for c in self.clips.values()]
        return sorted([r for r in rows if r[0] is not None], key=lambda r: (r[0], r[1].id))

    def device_clips(self, dev_id: str) -> list[Clip]:
        return [self.clips[c] for c in self.devices[dev_id].clips if c in self.clips]
